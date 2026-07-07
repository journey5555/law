"""SKT AIP Knowledge API 클라이언트 (Keycloak JWT 인증)"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

import requests
import urllib3

from config import (
    AGENT_VERIFY_SSL,
    KNOWLEDGE_BASE_URL,
    KNOWLEDGE_TOKEN,
    KNOWLEDGE_USER,
    KNOWLEDGE_PASSWORD,
)

if not AGENT_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("knowledge_api")

UPLOAD_URL = f"{KNOWLEDGE_BASE_URL}/datasources/upload/files"
LOGIN_URL  = f"{KNOWLEDGE_BASE_URL}/auth/login"

_cached_token: str | None = None


class KnowledgeApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class KnowledgeDuplicateError(KnowledgeApiError):
    """같은 이름의 파일이 이미 존재할 때 (406)"""


def _fetch_token() -> str:
    """아이디/비번으로 로그인하여 액세스 토큰 발급"""
    if not KNOWLEDGE_USER or not KNOWLEDGE_PASSWORD:
        raise KnowledgeApiError(
            "KNOWLEDGE_TOKEN 또는 KNOWLEDGE_USER/KNOWLEDGE_PASSWORD가 설정되지 않았습니다."
        )
    resp = requests.post(
        LOGIN_URL,
        data={"username": KNOWLEDGE_USER, "password": KNOWLEDGE_PASSWORD},
        timeout=30,
        verify=AGENT_VERIFY_SSL,
    )
    if not resp.ok:
        raise KnowledgeApiError(
            f"로그인 실패 ({resp.status_code}): {resp.text[:200]}",
            status_code=resp.status_code,
        )
    data = resp.json()
    token = data.get("access_token") or data.get("token") or data.get("data", {}).get("access_token")
    if not token:
        raise KnowledgeApiError(f"로그인 응답에서 토큰을 찾을 수 없습니다: {list(data.keys())}")
    logger.info("Knowledge 로그인 성공 (토큰 갱신)")
    return token


def _get_token() -> str:
    global _cached_token
    if _cached_token:
        return _cached_token
    if KNOWLEDGE_TOKEN:
        return KNOWLEDGE_TOKEN
    _cached_token = _fetch_token()
    return _cached_token


def _request(method: str, url: str, extra_headers: dict | None = None, **kwargs) -> requests.Response:
    """401 발생 시 토큰 갱신 후 1회 재시도"""
    global _cached_token

    def _make() -> requests.Response:
        h = {"Authorization": f"Bearer {_get_token()}"}
        if extra_headers:
            h.update(extra_headers)
        return requests.request(method, url, headers=h, verify=AGENT_VERIFY_SSL, **kwargs)

    resp = _make()
    if resp.status_code == 401 and (KNOWLEDGE_USER and KNOWLEDGE_PASSWORD):
        logger.info("401 — 토큰 만료, 재로그인 시도")
        _cached_token = None
        resp = _make()
    return resp


def upload_file(content: str | bytes, file_name: str) -> str:
    """
    Step 1 — 파일 업로드
    Returns: temp_file_path
    """
    if isinstance(content, str):
        content = content.encode("utf-8")

    if file_name.endswith(".json"):
        mime = "application/json"
    elif file_name.endswith(".pdf"):
        mime = "application/pdf"
    else:
        mime = "text/markdown"
    started = time.perf_counter()
    resp = _request(
        "POST", UPLOAD_URL,
        files={"files": (file_name, io.BytesIO(content), mime)},
        timeout=60,
    )
    elapsed = time.perf_counter() - started

    if not resp.ok:
        raise KnowledgeApiError(
            f"파일 업로드 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )

    data = resp.json()
    temp_path = data["data"][0]["temp_file_path"]
    logger.info("파일 업로드 완료 (%.1fs): %s → %s", elapsed, file_name, temp_path)
    return temp_path


def add_document_and_index(
    repo_id: str,
    temp_file_path: str,
    file_name: str,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """
    Step 2 — 문서 추가 + 인덱싱
    """
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/add_document_and_indexing"
    body: dict[str, Any] = {
        "document_file_info": {
            "temp_file_path": temp_file_path,
            "file_name": file_name,
        }
    }
    if metadata:
        body["document_metadata"] = metadata

    started = time.perf_counter()
    for attempt in range(2):
        resp = _request(
            "POST", url,
            extra_headers={"Content-Type": "application/json"},
            json=body,
            timeout=120,
        )
        if resp.ok:
            break
        if attempt == 0 and "No documents" in resp.text:
            # ponytail: temp file not yet visible on server side, retry once after delay
            time.sleep(3)
            continue
        if resp.status_code == 406 and "same name" in resp.text:
            raise KnowledgeDuplicateError(
                f"이미 존재하는 파일: {file_name}",
                status_code=406,
            )
        if "already in process" in resp.text or "already in progress" in resp.text:
            logger.info("인덱싱 이미 진행 중 (정상): %s", file_name)
            return resp.json() if resp.text else {}
        raise KnowledgeApiError(
            f"인덱싱 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )
    elapsed = time.perf_counter() - started

    if not resp.ok:
        raise KnowledgeApiError(
            f"인덱싱 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )

    logger.info("인덱싱 완료 (%.1fs): %s", elapsed, file_name)
    return resp.json()


def delete_documents(repo_id: str, doc_ids: list[str]) -> None:
    """document ID 목록을 Knowledge repo에서 삭제 (datasource + 임베딩 포함)"""
    if not doc_ids:
        return
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/documents"
    resp = _request(
        "DELETE", url,
        extra_headers={"Content-Type": "application/json"},
        json=doc_ids,
        timeout=60,
    )
    if not resp.ok:
        raise KnowledgeApiError(
            f"문서 삭제 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )
    logger.info("문서 삭제 완료: %d건", len(doc_ids))


def _hard_delete(resource_type: str, resource_id: str) -> None:
    url = f"{KNOWLEDGE_BASE_URL}/{resource_type}/{resource_id}/hard-delete"
    resp = _request("DELETE", url, timeout=120)
    if not resp.ok:
        raise KnowledgeApiError(
            f"{resource_type} hard_delete 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )
    logger.info("%s hard_delete 완료: %s", resource_type, resource_id)

def hard_delete_datasource(datasource_id: str) -> None:
    _hard_delete("datasources", datasource_id)

def hard_delete_dataset(dataset_id: str) -> None:
    _hard_delete("datasets", dataset_id)


def ingest(
    repo_id: str,
    content: str,
    file_name: str,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """upload → index 한 번에. 응답에 datasource_file_id 포함."""
    temp_path = upload_file(content, file_name)
    return add_document_and_index(repo_id, temp_path, file_name, metadata)


def get_document_status(repo_id: str, document_id: str) -> dict[str, Any]:
    """문서 상태 조회 (status, is_indexing, chunk_count 등)"""
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/documents/{document_id}"
    resp = _request("GET", url, timeout=30)
    if not resp.ok:
        raise KnowledgeApiError(
            f"문서 상태 조회 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )
    data = resp.json()
    # 응답이 {"data": {...}} 형태일 수 있음
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        return data["data"]
    return data


def list_documents(repo_id: str) -> list[dict]:
    """Knowledge repo의 전체 문서 목록 반환 (id, name, status 포함)"""
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/documents"
    docs: list[dict] = []
    page = 1
    while True:
        resp = _request("GET", url, params={"page": page, "size": 100}, timeout=30)
        if not resp.ok:
            raise KnowledgeApiError(
                f"문서 목록 조회 실패 ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )
        data = resp.json()
        docs.extend(data.get("data", []))
        last_page = data.get("payload", {}).get("pagination", {}).get("last_page", 1)
        if page >= last_page:
            break
        page += 1
    return docs


def list_document_names(repo_id: str) -> set[str]:
    """Knowledge repo의 모든 문서 파일명 set 반환 (중복 사전 체크용)"""
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/documents"
    names: set[str] = set()
    page = 1
    while True:
        resp = _request("GET", url, params={"page": page, "size": 100}, timeout=30)
        if not resp.ok:
            raise KnowledgeApiError(
                f"문서 목록 조회 실패 ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )
        data = resp.json()
        for doc in data.get("data", []):
            if name := doc.get("name"):
                names.add(name)
        last_page = data.get("payload", {}).get("pagination", {}).get("last_page", 1)
        if page >= last_page:
            break
        page += 1
    return names


def get_document_chunks(repo_id: str, document_id: str) -> dict[str, Any]:
    """문서의 청크 목록 조회 — 전체 페이지 수집"""
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/documents/{document_id}/chunks"
    all_chunks: list = []
    page = 1
    while True:
        resp = _request("GET", url, params={"page": page, "size": 100}, timeout=30)
        if not resp.ok:
            raise KnowledgeApiError(
                f"청크 조회 실패 ({resp.status_code}): {resp.text[:300]}",
                status_code=resp.status_code,
            )
        data = resp.json()
        chunks = data if isinstance(data, list) else data.get("data", [])
        if isinstance(chunks, list):
            all_chunks.extend(chunks)
        pagination = data.get("payload", {}).get("pagination", {}) if isinstance(data, dict) else {}
        last_page = pagination.get("last_page", 1)
        if page >= last_page:
            break
        page += 1
    return {"chunks": all_chunks, "count": len(all_chunks)}


def wait_for_embedding(repo_id: str, document_id: str, timeout_sec: int = 300, interval: int = 10) -> bool:
    """문서 임베딩 완료까지 polling. 완료 시 True, 타임아웃 시 False"""
    import time as _time
    deadline = _time.time() + timeout_sec
    while _time.time() < deadline:
        try:
            doc = get_document_status(repo_id, document_id)
            status = doc.get("status", "")
            is_indexing = doc.get("is_indexing", True)
            if status == "embedded" and not is_indexing:
                return True
            if status == "failed":
                logger.warning("임베딩 실패: %s", document_id)
                return False
        except KnowledgeApiError:
            pass
        _time.sleep(interval)
    logger.warning("임베딩 타임아웃 (%ds): %s", timeout_sec, document_id)
    return False


def search_by_document_id(repo_id: str, document_id: str, top_k: int = 20) -> str:
    """document_id 필터로 Knowledge 검색 → 청크 텍스트 합쳐서 반환"""
    url = f"{KNOWLEDGE_BASE_URL}/knowledge/repos/{repo_id}/retrieval"
    body = {
        "query_text": document_id,
        "repo_id":    repo_id,
        "retrieval_options": {
            "retrieval_mode": "sparse",
            "top_k":          top_k,
            "filter":         f'document_id eq "{document_id}"',
        },
    }
    resp = _request("POST", url, extra_headers={"Content-Type": "application/json"},
                    json=body, timeout=30)
    if not resp.ok:
        raise KnowledgeApiError(
            f"검색 실패 ({resp.status_code}): {resp.text[:300]}",
            status_code=resp.status_code,
        )
    data = resp.json()
    chunks = data.get("data", [])
    if not chunks:
        return ""
    # score 기준 정렬 후 텍스트 합치기
    chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
    return "\n\n".join(c.get("content", "") for c in chunks if c.get("content"))


# ── 마크다운 포맷터 ──────────────────────────────────────────────────────────

def law_to_markdown(law_data: dict[str, Any], *, articles: list | None = None) -> str:
    """get_law() 응답 → 마크다운. articles 지정 시 해당 조문만 포함."""
    name    = law_data.get("law_name") or law_data.get("법령명한글", "법령")
    dept    = law_data.get("ministry", "")
    ef_date = law_data.get("enforcement_date", "")

    lines = [f"# {name}", ""]
    if dept or ef_date:
        meta = " | ".join(filter(None, [
            f"소관부처: {dept}" if dept else "",
            f"시행일자: {ef_date}" if ef_date else "",
        ]))
        lines += [f"> {meta}", ""]

    for art in (articles if articles is not None else law_data.get("articles", [])):
        num   = art.get("조문번호", "")
        title = art.get("조문제목", "")
        header = f"제{num}조" + (f"({title})" if title else "")
        lines += [f"## {header}", ""]

        hangs = art.get("항") if isinstance(art.get("항"), list) else []
        if hangs:
            for hang in hangs:
                body = str(hang.get("항내용") or "").strip()
                if body:
                    lines += [body, ""]
                for ho in (hang.get("호") if isinstance(hang.get("호"), list) else []):
                    ho_body = str(ho.get("호내용") or "").strip()
                    if ho_body:
                        lines.append(f"- {ho_body}")
                if any(str(ho.get("호내용") or "").strip()
                       for ho in (hang.get("호") if isinstance(hang.get("호"), list) else [])):
                    lines.append("")
        else:
            body = str(art.get("조문내용") or "").strip()
            if body:
                lines += [body, ""]

    return "\n".join(lines)


def prec_to_markdown(prec_data: dict[str, Any]) -> str:
    """get_prec() 응답 → 마크다운"""
    name     = prec_data.get("case_name", "판례")
    case_no  = prec_data.get("case_no", "")
    court    = prec_data.get("court", "")
    date     = prec_data.get("date", "")

    lines = [f"# {name}", ""]
    meta = " | ".join(filter(None, [case_no, court, date]))
    if meta:
        lines += [f"> {meta}", ""]

    for label, key in [
        ("판시사항", "issues"),
        ("판결요지", "summary"),
        ("참조조문", "ref_articles"),
        ("참조판례", "ref_cases"),
    ]:
        val = str(prec_data.get(key) or "").strip()
        if val:
            lines += [f"## {label}", "", val, ""]

    content = str(prec_data.get("content") or "").strip()
    if content:
        lines += ["## 판례 전문", "", content, ""]

    return "\n".join(lines)
