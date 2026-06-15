"""Pharma Monitor 라우터 — /pharma/* 로 마운트"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from pharma.db import get_conn, init_db, new_id, now
from pharma.gmail_client import exchange_code, get_auth_url, is_connected, search_emails

logger = logging.getLogger("pharma")

router = APIRouter(prefix="/pharma", tags=["pharma"])

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
