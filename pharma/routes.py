"""Pharma Monitor 라우터 — /pharma/* 로 마운트"""
import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import json
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from pharma.db import get_conn, init_db, new_id, now
from pharma.gmail_client import exchange_code, get_attachment, get_auth_url, get_watch_status, is_connected, pull_and_process, search_emails, send_email, start_watch, stop_watch

logger = logging.getLogger("pharma")

router = APIRouter(prefix="/pharma", tags=["pharma"])

from collections import deque
_recent_messages: deque = deque(maxlen=50)
_sse_clients: list[asyncio.Queue] = []

_STATIC = Path(__file__).resolve().parent.parent / "web" / "static" / "pharma"


# ── 페이지 ────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def pharma_index():
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# ── OAuth ─────────────────────────────────────────────────────────
@router.get("/oauth/login")
async def pharma_oauth_login():
    return RedirectResponse(get_auth_url())


@router.get("/oauth/callback")
async def pharma_oauth_callback(code: str = "", error: str = ""):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth 오류: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="인증 코드 없음")
    exchange_code(code)
    return RedirectResponse("/pharma?connected=1")


@router.get("/api/oauth/status")
async def pharma_oauth_status():
    return {"connected": is_connected()}


# ── 약품 관리 ─────────────────────────────────────────────────────
class DrugIn(BaseModel):
    name:           str           = Field(..., min_length=1)
    description:    Optional[str] = None
    expected_date:  Optional[str] = None
    sender_filter:  Optional[str] = None
    keyword_filter: Optional[str] = None


@router.get("/api/drugs")
async def pharma_list_drugs():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT d.*, COUNT(r.id) as result_count
            FROM drugs d LEFT JOIN results r ON r.drug_id = d.id
            GROUP BY d.id ORDER BY d.created_at DESC
        """).fetchall()
    return {"drugs": [dict(r) for r in rows]}


@router.post("/api/drugs", status_code=201)
async def pharma_add_drug(body: DrugIn):
    drug = {
        "id": new_id(), "name": body.name, "description": body.description,
        "expected_date": body.expected_date, "sender_filter": body.sender_filter,
        "keyword_filter": body.keyword_filter, "created_at": now(), "status": "pending",
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO drugs VALUES (:id,:name,:description,:expected_date,:sender_filter,:keyword_filter,:created_at,:status)",
            drug,
        )
    return drug


@router.put("/api/drugs/{drug_id}")
async def pharma_update_drug(drug_id: str, body: DrugIn):
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM drugs WHERE id=?", (drug_id,)).fetchone():
            raise HTTPException(status_code=404, detail="약품을 찾을 수 없습니다")
        conn.execute(
            "UPDATE drugs SET name=?,description=?,expected_date=?,sender_filter=?,keyword_filter=? WHERE id=?",
            (body.name, body.description, body.expected_date, body.sender_filter, body.keyword_filter, drug_id),
        )
    return {"ok": True}


@router.delete("/api/drugs/{drug_id}", status_code=204)
async def pharma_delete_drug(drug_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE drug_id=?", (drug_id,))
        conn.execute("DELETE FROM results WHERE drug_id=?", (drug_id,))
        conn.execute("DELETE FROM drugs WHERE id=?", (drug_id,))


# ── 수신 이력 ─────────────────────────────────────────────────────
@router.get("/api/results")
async def pharma_list_results(drug_id: Optional[str] = None):
    with get_conn() as conn:
        if drug_id:
            rows = conn.execute(
                "SELECT r.*, d.name as drug_name FROM results r LEFT JOIN drugs d ON r.drug_id=d.id WHERE r.drug_id=? ORDER BY r.received_at DESC",
                (drug_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT r.*, d.name as drug_name FROM results r LEFT JOIN drugs d ON r.drug_id=d.id ORDER BY r.received_at DESC"
            ).fetchall()
    return {"results": [dict(r) for r in rows]}


@router.get("/api/results/{result_id}")
async def pharma_get_result(result_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT r.*, d.name as drug_name FROM results r LEFT JOIN drugs d ON r.drug_id=d.id WHERE r.id=?",
            (result_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다")
    return dict(row)


# ── 알림 ─────────────────────────────────────────────────────────
@router.get("/api/alerts")
async def pharma_list_alerts():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.*, d.name as drug_name FROM alerts a LEFT JOIN drugs d ON a.drug_id=d.id ORDER BY a.created_at DESC"
        ).fetchall()
    return {"alerts": [dict(r) for r in rows]}


@router.post("/api/alerts/{alert_id}/read", status_code=204)
async def pharma_mark_alert_read(alert_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET read=1 WHERE id=?", (alert_id,))


@router.post("/api/alerts/read-all", status_code=204)
async def pharma_mark_all_alerts_read():
    with get_conn() as conn:
        conn.execute("UPDATE alerts SET read=1")


@router.delete("/api/alerts/{alert_id}", status_code=204)
async def pharma_delete_alert(alert_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))


# ── 통계 ─────────────────────────────────────────────────────────
@router.get("/api/stats")
async def pharma_stats():
    with get_conn() as conn:
        total_drugs   = conn.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
        received      = conn.execute("SELECT COUNT(*) FROM drugs WHERE status='received'").fetchone()[0]
        overdue       = conn.execute("SELECT COUNT(*) FROM drugs WHERE status='overdue'").fetchone()[0]
        pending       = conn.execute("SELECT COUNT(*) FROM drugs WHERE status='pending'").fetchone()[0]
        total_results = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        unread_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0]
        recent_results = conn.execute(
            "SELECT r.subject, r.received_at, d.name as drug_name FROM results r LEFT JOIN drugs d ON r.drug_id=d.id ORDER BY r.received_at DESC LIMIT 5"
        ).fetchall()
    return {
        "total_drugs": total_drugs, "received": received, "overdue": overdue,
        "pending": pending, "total_results": total_results, "unread_alerts": unread_alerts,
        "recent_results": [dict(r) for r in recent_results],
    }


# ── Gmail API 테스트 ──────────────────────────────────────────────
@router.get("/api/test/search")
async def pharma_test_search(q: str = "", max_results: int = 10):
    if not is_connected():
        raise HTTPException(status_code=403, detail="Gmail이 연결되지 않았습니다")
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요")
    try:
        emails = search_emails(q.strip(), max_results=min(max_results, 50))
        return {"count": len(emails), "emails": emails}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/api/pubsub/stream")
async def pharma_pubsub_stream(request: Request):
    """SSE — 새 메일 도착 시 즉시 프론트로 push"""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_clients.append(queue)

    async def event_gen():
        try:
            yield "data: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 연결 유지
        finally:
            _sse_clients.remove(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/watch/status")
async def pharma_watch_status():
    return get_watch_status()

@router.post("/api/watch/start")
async def pharma_watch_start():
    if not is_connected():
        raise HTTPException(status_code=403, detail="Gmail이 연결되지 않았습니다")
    try:
        return start_watch()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

@router.post("/api/watch/stop")
async def pharma_watch_stop():
    try:
        stop_watch()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/api/attachment")
async def pharma_get_attachment(message_id: str, attachment_id: str, mime_type: str = "application/octet-stream", filename: str = "attachment"):
    if not is_connected():
        raise HTTPException(status_code=403, detail="Gmail이 연결되지 않았습니다")
    try:
        from urllib.parse import quote
        data = get_attachment(message_id, attachment_id)
        encoded = quote(filename, safe="")
        return Response(content=data, media_type=mime_type,
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded}"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── 인보이스 추출 (Knowledge 검색 → LLM → JSON) ──────────────────
_EXTRACT_PROMPT = """\
You are an AI assistant.

Extract all information from the expense report document in the context.

<context>
{context}
</context>

Return ONLY a valid JSON object.

Rules:
- Do not output markdown.
- Do not output explanations.
- If a value cannot be found, return null.
- Numbers must be returned without commas.
- Keep the items array even if there is only one item.

JSON Schema:
{{
  "document_id": "",
  "created_date": "",
  "department": "",
  "contract_no": "",
  "project_name": "",
  "vendor": {{
    "company_name": "",
    "representative": "",
    "business_registration_no": "",
    "contact": "",
    "account_no": ""
  }},
  "payment": {{
    "method": "",
    "scheduled_date": ""
  }},
  "items": [
    {{
      "name": "",
      "quantity": "",
      "unit_price": 0,
      "amount": 0,
      "remark": ""
    }}
  ],
  "total": {{
    "amount": 0,
    "amount_korean": ""
  }},
  "attachments": [],
  "description": "",
  "remark": ""
}}"""


@router.post("/api/extract")
async def pharma_extract(body: dict):
    """document_id → Knowledge 청크 직접 조회 → LLM 추출 → JSON 반환"""
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import get_document_chunks, KnowledgeApiError
    from clients.agent_client import build_invoke_body, _require_api_key, _agent_url
    import requests as _req
    from config import PHARMA_KNOWLEDGE_AGENT_ID, PHARMA_KNOWLEDGE_API_KEY

    document_id = body.get("document_id", "").strip()
    repo_id     = body.get("repo_id", "").strip() or PHARMA_KNOWLEDGE_REPO_ID
    if not document_id:
        raise HTTPException(status_code=400, detail="document_id가 필요합니다")
    if not repo_id:
        raise HTTPException(status_code=400, detail="PHARMA_KNOWLEDGE_REPO_ID가 설정되지 않았습니다")

    # 1. attachment_hashes에서 knowledge_id 조회
    with get_conn() as conn:
        row = conn.execute(
            "SELECT knowledge_id FROM attachment_hashes WHERE doc_id=?", (document_id,)
        ).fetchone()
    knowledge_id = row["knowledge_id"] if row else None
    if not knowledge_id:
        raise HTTPException(status_code=404, detail=f"knowledge_id 없음 — 인덱싱 완료 후 시도하세요: {document_id}")

    # 2. 청크 직접 조회
    try:
        result  = await asyncio.to_thread(get_document_chunks, repo_id, knowledge_id)
        chunks  = result.get("chunks", [])
        context = "\n\n".join(
            c.get("content") or c.get("text") or c.get("chunk_text", "") for c in chunks
        ).strip()
    except KnowledgeApiError as e:
        raise HTTPException(status_code=502, detail=f"Knowledge 청크 조회 실패: {e}") from e

    if not context:
        raise HTTPException(status_code=404, detail=f"문서 내용 없음: {document_id}")

    # 2. LLM 추출
    prompt = _EXTRACT_PROMPT.format(context=context)
    try:
        api_key = _require_api_key(PHARMA_KNOWLEDGE_API_KEY)
        url     = _agent_url("/invoke", PHARMA_KNOWLEDGE_AGENT_ID)
        resp    = await asyncio.to_thread(
            lambda: _req.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=build_invoke_body(prompt),
                timeout=60,
                verify=False,
            )
        )
        if not resp.ok:
            raise HTTPException(status_code=502, detail=f"LLM 오류: {resp.text[:200]}")
        raw = resp.json()
        # 응답 구조에서 텍스트 추출 (여러 구조 대응)
        out = raw.get("output") or raw.get("data") or raw
        if isinstance(out, dict):
            msgs = out.get("messages", [])
            text = (msgs[-1].get("content", "") if msgs else "") or out.get("content", "") or str(raw)
        else:
            text = str(out)
        # 마크다운 코드블록 제거
        import re as _re, json as _json
        text = _re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
        # JSON 부분만 추출
        m = _re.search(r"\{[\s\S]+\}", text)
        if not m:
            logger.warning("LLM 응답에서 JSON 못 찾음: %s", text[:300])
            raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")
        result = _json.loads(m.group())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"추출 오류: {e}") from e

    return {"document_id": document_id, "extracted": result}


# ── Excel 생성 ────────────────────────────────────────────────────
@router.post("/api/excel/generate")
async def pharma_excel_generate(body: dict):
    from pharma.excel import generate
    from urllib.parse import quote
    try:
        xlsx = await asyncio.to_thread(generate, body)
        doc_id = body.get("document_id", "지출결의서")
        fname  = f"{doc_id}.xlsx"
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── 로컬 첨부파일 서빙 ────────────────────────────────────────────
@router.get("/api/attachment/page")
async def pharma_attachment_page(filename: str, page: int = 0, token: str = ""):
    """PDF 특정 페이지를 JPEG로 반환 (Tool Node용)"""
    import fitz
    from config import PHARMA_OCR_TOKEN
    if PHARMA_OCR_TOKEN and token != PHARMA_OCR_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    base = Path(__file__).resolve().parent.parent / "data" / "pharma_attachments"
    path = (base / filename).resolve()
    if not str(path).startswith(str(base)) or not path.exists():
        raise HTTPException(status_code=404)
    doc = fitz.open(str(path))
    if page >= len(doc):
        raise HTTPException(status_code=400, detail=f"페이지 범위 초과 (총 {len(doc)}페이지)")
    pix  = doc[page].get_pixmap(dpi=120)
    doc.close()
    return Response(content=pix.tobytes("jpeg"), media_type="image/jpeg")


@router.get("/api/attachment/local")
async def pharma_local_attachment(filename: str):
    import mimetypes
    base = Path(__file__).resolve().parent.parent / "data" / "pharma_attachments"
    path = (base / filename).resolve()
    if not str(path).startswith(str(base)):
        raise HTTPException(status_code=403)
    if not path.exists():
        raise HTTPException(status_code=404)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    from urllib.parse import quote
    return Response(content=path.read_bytes(), media_type=mime,
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"})


@router.get("/api/attachments")
async def pharma_list_attachments():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, filename, saved_at, knowledge_id FROM attachment_hashes ORDER BY saved_at DESC"
        ).fetchall()
    return {"attachments": [dict(r) for r in rows]}


@router.get("/api/attachment/status/{doc_id:path}")
async def pharma_attachment_status(doc_id: str):
    """Knowledge 인덱싱 상태 확인"""
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import get_document_status, KnowledgeApiError
    with get_conn() as conn:
        row = conn.execute(
            "SELECT knowledge_id FROM attachment_hashes WHERE doc_id=?", (doc_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="첨부파일 없음")
    k_id = row["knowledge_id"]
    if not k_id:
        return {"status": "uploading", "ready": False}
    try:
        info = get_document_status(PHARMA_KNOWLEDGE_REPO_ID, k_id)
        status = info.get("status", "")
        ready  = status == "embedded" and not info.get("is_indexing", True)
        return {"status": status, "ready": ready, "knowledge_id": k_id}
    except KnowledgeApiError as e:
        if e.status_code == 404:
            return {"status": "deleted", "ready": False}
        return {"status": "unknown", "ready": False}


@router.post("/api/attachments/import")
async def pharma_import_attachments():
    """Knowledge repo의 전체 문서를 attachment_hashes에 임포트"""
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import list_documents, KnowledgeApiError
    if not PHARMA_KNOWLEDGE_REPO_ID:
        raise HTTPException(status_code=400, detail="PHARMA_KNOWLEDGE_REPO_ID 미설정")
    try:
        docs = await asyncio.to_thread(list_documents, PHARMA_KNOWLEDGE_REPO_ID)
    except KnowledgeApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    imported = 0
    with get_conn() as conn:
        existing_kids = {r[0] for r in conn.execute(
            "SELECT knowledge_id FROM attachment_hashes WHERE knowledge_id IS NOT NULL"
        ).fetchall()}
        for doc in docs:
            k_id   = doc.get("id") or doc.get("document_id") or ""
            fname  = doc.get("name") or doc.get("file_name") or k_id
            status = doc.get("status", "")
            if not k_id or k_id in existing_kids:
                continue
            doc_id = fname
            conn.execute(
                "INSERT OR IGNORE INTO attachment_hashes VALUES (?,?,?,?,?)",
                (f"imported_{k_id}", doc_id, fname, now(), k_id),
            )
            imported += 1
    return {"imported": imported}


@router.post("/api/attachments/sync")
async def pharma_sync_attachments():
    """Knowledge에 없는 첨부파일 재업로드"""
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import upload_file, add_document_and_index, get_document_status, KnowledgeApiError
    if not PHARMA_KNOWLEDGE_REPO_ID:
        return {"reupload": 0}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, knowledge_id FROM attachment_hashes WHERE knowledge_id IS NOT NULL"
        ).fetchall()
    save_dir = Path(__file__).resolve().parent.parent / "data" / "pharma_attachments"
    reuploaded = []
    for row in rows:
        try:
            await asyncio.to_thread(get_document_status, PHARMA_KNOWLEDGE_REPO_ID, row["knowledge_id"])
        except KnowledgeApiError as e:
            if e.status_code != 404:
                continue
            local_path = save_dir / row["doc_id"]
            if not local_path.exists():
                logger.warning("로컬 파일 없음, 재업로드 불가: %s", row["doc_id"])
                continue
            try:
                data      = local_path.read_bytes()
                temp_path = await asyncio.to_thread(upload_file, data, row["doc_id"])
                result    = await asyncio.to_thread(
                    add_document_and_index, PHARMA_KNOWLEDGE_REPO_ID, temp_path,
                    row["doc_id"], {"document_id": row["doc_id"]}
                )
                k_id = (result.get("data") or result).get("document_id") or (result.get("data") or result).get("id")
                with get_conn() as conn:
                    conn.execute("UPDATE attachment_hashes SET knowledge_id=? WHERE doc_id=?",
                                 (k_id, row["doc_id"]))
                reuploaded.append(row["doc_id"])
                logger.info("Knowledge 재업로드 완료: %s", row["doc_id"])
            except Exception as ex:
                logger.error("재업로드 실패 (%s): %s", row["doc_id"], ex)
    return {"reupload": len(reuploaded), "doc_ids": reuploaded}


@router.get("/api/history")
async def pharma_history():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, doc_id, filename, sent_to, subject, sent_at FROM send_history ORDER BY sent_at DESC"
        ).fetchall()
    return {"history": [dict(r) for r in rows]}


@router.post("/api/history")
async def pharma_save_history(body: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO send_history VALUES (?,?,?,?,?,?,?)",
            (new_id(), body.get("doc_id",""), body.get("filename",""),
             body.get("sent_to",""), body.get("subject",""),
             now(), json.dumps(body.get("data"), ensure_ascii=False)),
        )


# ── SHA-256 중복 체크 테스트 ─────────────────────────────────────
@router.post("/api/dedup/check")
async def pharma_dedup_check(file: UploadFile = File(...)):
    """파일 SHA-256 계산 → DB 중복 여부 반환"""
    data   = await file.read()
    sha256 = hashlib.sha256(data).hexdigest()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT doc_id, filename, saved_at FROM attachment_hashes WHERE sha256=?", (sha256,)
        ).fetchone()
    if row:
        return {"duplicate": True,  "sha256": sha256, "existing": dict(row)}
    return    {"duplicate": False, "sha256": sha256}


# ── 내용 기반 2차 중복 체크 ──────────────────────────────────────
@router.post("/api/dedup/content-check")
async def pharma_dedup_content_check(body: dict):
    """추출된 JSON 핵심 필드(문서번호·업체명·금액·작성일자)를 send_history와 비교"""
    data = body.get("data") or {}

    def _key(d):
        v = d.get("vendor") or {}
        t = d.get("total")  or {}
        return {
            "document_id":   (d.get("document_id") or "").strip(),
            "company_name":  (v.get("company_name") or "").strip(),
            "amount":        str(t.get("amount") or "").strip(),
            "created_date":  (d.get("created_date") or "").strip(),
        }

    target = _key(data)
    # 비어있는 필드만 있으면 비교 불가
    filled = [v for v in target.values() if v]
    if not filled:
        raise HTTPException(status_code=400, detail="비교할 필드가 없습니다. 먼저 추출을 완료하세요.")

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, doc_id, filename, sent_at, extracted_json FROM send_history ORDER BY sent_at DESC"
        ).fetchall()

    matches = []
    for row in rows:
        try:
            hist = json.loads(row["extracted_json"] or "{}")
        except Exception:
            continue
        cand = _key(hist)
        matched_fields = [k for k in target if target[k] and target[k] == cand[k]]
        if len(matched_fields) >= 2:
            matches.append({
                "id":       row["id"],
                "doc_id":   row["doc_id"],
                "filename": row["filename"],
                "sent_at":  row["sent_at"],
                "matched_fields": matched_fields,
                "match_count": len(matched_fields),
            })

    matches.sort(key=lambda x: -x["match_count"])
    return {"target": target, "matches": matches, "duplicate": len(matches) > 0}


# ── OCR 에이전트 테스트 ───────────────────────────────────────────
@router.post("/api/ocr/test")
async def pharma_ocr_test(file: UploadFile = File(...)):
    """PDF 업로드 → 임시 저장 → HTTP URL → 에이전트 Tool Node OCR"""
    import json as _json
    from config import PHARMA_KNOWLEDGE_AGENT_ID, PHARMA_KNOWLEDGE_API_KEY as _PHARMA_KEY, \
                       PHARMA_EXTERNAL_URL, PHARMA_OCR_TOKEN
    from clients.agent_client import _require_api_key, _agent_url
    import requests as _req

    if not PHARMA_KNOWLEDGE_AGENT_ID:
        raise HTTPException(status_code=400, detail="PHARMA_KNOWLEDGE_AGENT_ID 미설정")

    import base64, fitz
    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    # 40 DPI + JPEG quality 40 — 최소 크기
    pix = doc[0].get_pixmap(dpi=40)
    b64 = base64.b64encode(pix.tobytes("jpeg", jpg_quality=40)).decode()
    doc.close()
    logger.info("OCR base64 크기: %d chars", len(b64))

    try:
        message = _json.dumps({"url": f"data:image/jpeg;base64,{b64}"})
        body = {
            "config": {},
            "input": {"messages": [{"content": message, "type": "human"}]},
            "kwargs": {},
        }

        api_key = _require_api_key(_PHARMA_KEY)
        url     = _agent_url("/invoke", PHARMA_KNOWLEDGE_AGENT_ID)
        resp    = await asyncio.to_thread(
            lambda: _req.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                              json=body, timeout=120, verify=False)
        )
        return {"status": resp.status_code, "response": resp.json() if resp.ok else resp.text[:1000]}
    except Exception as e:
        return {"status": 0, "response": f"연결 실패: {e}"}


# ── Excel 발송 ────────────────────────────────────────────────────
class ExcelSendIn(BaseModel):
    to: str
    subject: str = "지출결의서"
    body: str = "지출결의서를 첨부합니다."
    data: dict  # 지출결의서 JSON

@router.post("/api/excel/send")
async def pharma_excel_send(req: ExcelSendIn):
    if not is_connected():
        raise HTTPException(status_code=403, detail="Gmail이 연결되지 않았습니다")
    from pharma.excel import generate
    try:
        xlsx = await asyncio.to_thread(generate, req.data)
        doc_id = req.data.get("document_id", "지출결의서")
        fname  = f"{doc_id}.xlsx"
        msg_id = await asyncio.to_thread(send_email, req.to, req.subject, req.body, xlsx, fname)
        return {"ok": True, "message_id": msg_id}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── Knowledge 업로드 ──────────────────────────────────────────────
@router.post("/api/upload")
async def pharma_upload(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    repo_id: str = Form(""),
):
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import upload_file, add_document_and_index, KnowledgeApiError
    rid = repo_id.strip() or PHARMA_KNOWLEDGE_REPO_ID
    if not rid:
        raise HTTPException(status_code=400, detail="PHARMA_KNOWLEDGE_REPO_ID가 설정되지 않았습니다")

    content = await file.read()
    fname = f"{document_id}_{file.filename}"
    try:
        temp_path = await asyncio.to_thread(upload_file, content, fname)
        result = await asyncio.to_thread(
            add_document_and_index, rid, temp_path, fname,
            {"document_id": document_id},
        )
        return {"ok": True, "document_id": document_id, "file_name": fname, "result": result}
    except KnowledgeApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── 수동 동기화 ───────────────────────────────────────────────────
@router.post("/api/sync")
async def pharma_manual_sync():
    if not is_connected():
        raise HTTPException(status_code=403, detail="Gmail이 연결되지 않았습니다")
    count = await _run_sync()
    return {"synced": count}


# ── 스케줄러 작업 (web/app.py 에서 호출) ─────────────────────────
async def sync_emails_job():
    if not is_connected():
        return
    try:
        count = await _run_sync()
        if count:
            logger.info("이메일 동기화: %d건 신규", count)
    except Exception as e:
        logger.error("이메일 동기화 오류: %s", e)


def _save_attachment_local(msg_id: str, att: dict):
    """첨부파일 로컬 저장 + DB 등록 (빠름). 성공 시 (doc_id, sha256, data) 반환, 중복/오류 시 None."""
    import hashlib, re
    fname  = att.get("filename", "attachment")
    safe   = re.sub(r'[\\/:*?"<>|]', '_', fname)[:80]
    doc_id = f"{msg_id[:8]}_{safe}"
    save_dir = Path(__file__).resolve().parent.parent / "data" / "pharma_attachments"
    save_dir.mkdir(parents=True, exist_ok=True)
    try:
        data   = get_attachment(msg_id, att["attachment_id"])
        sha256 = hashlib.sha256(data).hexdigest()
        with get_conn() as conn:
            existing = conn.execute("SELECT doc_id FROM attachment_hashes WHERE sha256=?", (sha256,)).fetchone()
            if existing:
                logger.info("첨부파일 중복 건너뜀: %s (이전 doc_id=%s)", fname, existing["doc_id"])
                return None
            conn.execute("INSERT INTO attachment_hashes VALUES (?,?,?,?,NULL)", (sha256, doc_id, fname, now()))
        (save_dir / doc_id).write_bytes(data)
        logger.info("첨부파일 로컬 저장: %s", doc_id)
        return doc_id, sha256, data
    except Exception as e:
        logger.error("첨부파일 로컬 저장 오류 (%s): %s", fname, e)
        return None


def _upload_to_knowledge(doc_id: str, sha256: str, data: bytes) -> None:
    """Knowledge API 업로드 (느림). 백그라운드 태스크에서 실행."""
    from config import PHARMA_KNOWLEDGE_REPO_ID
    from clients.knowledge_client import upload_file, add_document_and_index, KnowledgeApiError
    if not PHARMA_KNOWLEDGE_REPO_ID:
        return
    try:
        temp_path = upload_file(data, doc_id)
        result    = add_document_and_index(PHARMA_KNOWLEDGE_REPO_ID, temp_path, doc_id, {"document_id": doc_id})
        k_id = (result.get("data") or result).get("document_id") or (result.get("data") or result).get("id")
        if k_id:
            with get_conn() as conn:
                conn.execute("UPDATE attachment_hashes SET knowledge_id=? WHERE sha256=?", (k_id, sha256))
        logger.info("Knowledge 업로드 완료: %s (knowledge_id=%s)", doc_id, k_id)
    except KnowledgeApiError as e:
        logger.error("Knowledge 업로드 실패 (%s): %s", doc_id, e)
    except Exception as e:
        logger.error("Knowledge 업로드 오류 (%s): %s", doc_id, e)


async def pubsub_pull_job():
    """Pub/Sub pull → 새 메일 처리 (30초마다)"""
    from config import PUBSUB_PROJECT_ID
    if not PUBSUB_PROJECT_ID:
        return
    try:
        new_msgs = await asyncio.to_thread(pull_and_process)
        if not new_msgs:
            return
        for m in new_msgs:
            _recent_messages.appendleft(m)
            # 로컬 저장 먼저 (빠름) → SSE broadcast → Knowledge 업로드는 백그라운드
            saved = []
            for att in m.get("attachments", []):
                if att.get("attachment_id"):
                    r = await asyncio.to_thread(_save_attachment_local, m["id"], att)
                    if r:
                        saved.append(r)
            for q in list(_sse_clients):
                await q.put(m)
            for doc_id, sha256, data in saved:
                asyncio.create_task(asyncio.to_thread(_upload_to_knowledge, doc_id, sha256, data))
        with get_conn() as conn:
            drugs = [dict(r) for r in conn.execute("SELECT * FROM drugs").fetchall()]
        for msg in new_msgs:
            for drug in drugs:
                sender_ok  = not drug.get("sender_filter")  or drug["sender_filter"]  in msg.get("sender", "")
                keyword_ok = not drug.get("keyword_filter") or drug["keyword_filter"] in (msg.get("subject", "") + msg.get("body", ""))
                if not (sender_ok and keyword_ok):
                    continue
                with get_conn() as conn:
                    if conn.execute("SELECT id FROM results WHERE email_message_id=?", (msg["id"],)).fetchone():
                        continue
                    conn.execute(
                        "INSERT INTO results (id,drug_id,email_message_id,sender,subject,received_at,summary,raw_body,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id(), drug["id"], msg["id"], msg["sender"], msg["subject"],
                         msg["date"], msg["body"][:500], msg["body"], now()),
                    )
                    conn.execute("UPDATE drugs SET status='received' WHERE id=?", (drug["id"],))
                    conn.execute(
                        "INSERT INTO alerts (id,drug_id,alert_type,message,created_at,read) VALUES (?,?,?,?,?,0)",
                        (new_id(), drug["id"], "received",
                         f"'{drug['name']}' 결과 메일 수신: {msg['subject']}", now()),
                    )
                    logger.info("Pub/Sub 신규 메일 처리: %s → %s", drug["name"], msg["subject"])
    except Exception as e:
        logger.error("Pub/Sub pull job 오류: %s", e)


async def watch_renewal_job():
    """Gmail watch 만료 전 자동 갱신 (매일)"""
    from config import PUBSUB_PROJECT_ID
    if not PUBSUB_PROJECT_ID:
        return
    try:
        status = get_watch_status()
        if not status.get("active") or status.get("remaining_h", 999) < 25:
            await asyncio.to_thread(start_watch)
            logger.info("Gmail watch 자동 갱신 완료")
    except Exception as e:
        logger.error("watch 갱신 오류: %s", e)


async def check_overdue_job():
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        drugs = [dict(r) for r in conn.execute(
            "SELECT * FROM drugs WHERE expected_date IS NOT NULL AND expected_date < ? AND status='pending'",
            (today,),
        ).fetchall()]
        for drug in drugs:
            if conn.execute(
                "SELECT id FROM alerts WHERE drug_id=? AND alert_type='overdue' AND date(created_at)=date('now','localtime')",
                (drug["id"],),
            ).fetchone():
                continue
            conn.execute(
                "INSERT INTO alerts (id,drug_id,alert_type,message,created_at,read) VALUES (?,?,?,?,?,0)",
                (new_id(), drug["id"], "overdue",
                 f"'{drug['name']}' 결과 메일 미수신 (예정일: {drug['expected_date']})", now()),
            )
            conn.execute("UPDATE drugs SET status='overdue' WHERE id=?", (drug["id"],))
            logger.warning("미수신 감지: %s (예정일: %s)", drug["name"], drug["expected_date"])


async def _run_sync() -> int:
    with get_conn() as conn:
        drugs = [dict(r) for r in conn.execute("SELECT * FROM drugs").fetchall()]
    total = 0
    for drug in drugs:
        parts = []
        if drug.get("sender_filter"):
            parts.append(f"from:{drug['sender_filter']}")
        if drug.get("keyword_filter"):
            parts.append(drug["keyword_filter"])
        if not parts:
            continue
        try:
            emails = search_emails(" ".join(parts), max_results=20)
            for email in emails:
                with get_conn() as conn:
                    if conn.execute("SELECT id FROM results WHERE email_message_id=?", (email["id"],)).fetchone():
                        continue
                    conn.execute(
                        "INSERT INTO results (id,drug_id,email_message_id,sender,subject,received_at,summary,raw_body,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (new_id(), drug["id"], email["id"], email["sender"], email["subject"],
                         email["date"], email["body"][:500], email["body"], now()),
                    )
                    conn.execute("UPDATE drugs SET status='received' WHERE id=?", (drug["id"],))
                    conn.execute(
                        "INSERT INTO alerts (id,drug_id,alert_type,message,created_at,read) VALUES (?,?,?,?,?,0)",
                        (new_id(), drug["id"], "received",
                         f"'{drug['name']}' 결과 메일 수신: {email['subject']}", now()),
                    )
                    total += 1
        except Exception as e:
            logger.error("'%s' 동기화 오류: %s", drug["name"], e)
    return total
