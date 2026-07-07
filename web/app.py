"""에이전트 채팅 웹 서버"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
import logging
import logging.handlers
import socket
import time
import uuid
from datetime import datetime
from typing import Optional

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from clients.agent_client import AgentApiError, invoke_agent, stream_agent_tokens
from clients.knowledge_client import KnowledgeApiError, KnowledgeDuplicateError, delete_documents, hard_delete_datasource, ingest, get_document_status, get_document_chunks, list_document_names, law_to_markdown, prec_to_markdown
from clients.law_client import LawApiError, format_jo, get_law, get_prec, search_law, search_prec
from config import (
    AGENT_API_KEY, AGENT_ID, CHAT_HOST, CHAT_PORT, LOG_LEVEL,
    KNOWLEDGE_LAW_REPO_ID, KNOWLEDGE_PREC_REPO_ID, KNOWLEDGE_SUMM_REPO_ID,
    SUMMARIZE_AGENT_ID, SUMMARIZE_API_KEY,
    LAW_PREC_AGENT_ID, LAW_PREC_AGENT_API_KEY,
    LAW_PREC_TEST_AGENT_ID, LAW_PREC_TEST_AGENT_API_KEY,
    LAW_KEYWORD_AGENT_ID, LAW_KEYWORD_AGENT_API_KEY,
    PHARMA_CHECK_INTERVAL_MIN,
)

from config import PHARMA_ENABLED
if PHARMA_ENABLED:
    from pharma.db import init_db as pharma_init_db
    from pharma.routes import router as pharma_router, sync_emails_job, check_overdue_job, pubsub_pull_job, watch_renewal_job

_ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = _ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_level = getattr(logging, LOG_LEVEL, logging.INFO)
_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_file_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "agent.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(_formatter)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_formatter)

logging.root.setLevel(_log_level)
logging.root.addHandler(_file_handler)
logging.root.addHandler(_console_handler)

logger = logging.getLogger("chat_server")

_scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
_law_lock  = asyncio.Lock()
_prec_lock = asyncio.Lock()
_prec_batch_cancel = False


# ── 파일 경로 ──────────────────────────────────────────────────
_DATA_DIR              = _ROOT_DIR / "data"
BATCH_LAW_CONFIG_FILE  = _DATA_DIR / "batch_config.json"
BATCH_PREC_CONFIG_FILE = _DATA_DIR / "batch_prec_config.json"
BATCHTEST_CONFIG_FILE  = _DATA_DIR / "batchtest_config.json"
LAW_STATES_FILE        = _DATA_DIR / "law_states.json"
PREC_STATES_FILE       = _DATA_DIR / "prec_states.json"
BATCH_LAW_LOGS_FILE    = _DATA_DIR / "batch_logs.json"
BATCH_PREC_LOGS_FILE   = _DATA_DIR / "batch_prec_logs.json"
NOTIFICATIONS_FILE     = _DATA_DIR / "notifications.json"
BATCHTEST_DOCS_DIR     = _DATA_DIR / "batchtest_docs"


def _load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if default is not None:
        return json.loads(json.dumps(default))
    return {}

def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_batch_law_config():  return _load_json(BATCH_LAW_CONFIG_FILE, {"run_time": "02:00", "laws": []})
def _save_batch_law_config(d): _save_json(BATCH_LAW_CONFIG_FILE, d)
def _load_batch_prec_config(): return _load_json(BATCH_PREC_CONFIG_FILE, {"run_time": "03:00", "laws": []})
def _save_batch_prec_config(d): _save_json(BATCH_PREC_CONFIG_FILE, d)
def _load_law_states():        return _load_json(LAW_STATES_FILE)
def _save_law_states(d):       _save_json(LAW_STATES_FILE, d)
def _save_prec_states(d):      _save_json(PREC_STATES_FILE, d)
def _load_batch_law_logs():    return _load_json(BATCH_LAW_LOGS_FILE, [])
def _save_batch_law_logs(d):   _save_json(BATCH_LAW_LOGS_FILE, d)
def _load_batch_prec_logs():   return _load_json(BATCH_PREC_LOGS_FILE, [])
def _save_batch_prec_logs(d):  _save_json(BATCH_PREC_LOGS_FILE, d)
def _load_batchtest_config():  return _load_json(BATCHTEST_CONFIG_FILE, {"enabled": False, "run_time": "02:00", "target": "prec", "repo": "prec", "count": 0, "concurrent": 1})
def _save_batchtest_config(d): _save_json(BATCHTEST_CONFIG_FILE, d)
def _load_notifications():     return _load_json(NOTIFICATIONS_FILE, {"notifications": []})
def _save_notifications(d):    _save_json(NOTIFICATIONS_FILE, d)

def _load_prec_states() -> dict:
    if PREC_STATES_FILE.exists():
        return _load_json(PREC_STATES_FILE)
    if LAW_STATES_FILE.exists():
        law_states  = _load_json(LAW_STATES_FILE)
        prec_states = {}
        for name, state in law_states.items():
            entry = {k: state[k] for k in ("uploaded_prec_ids", "last_prec_count", "last_prec_knowledge_upload") if k in state}
            if entry:
                prec_states[name] = entry
        if prec_states:
            _save_json(PREC_STATES_FILE, prec_states)
            logger.info("prec_states 마이그레이션 완료: %d건", len(prec_states))
        return prec_states
    return {}

def _push_notification(ndata: dict, ntype: str, law_name: str, title: str, body: str,
                        preview: Optional[dict] = None) -> None:
    ndata["notifications"].insert(0, {
        "id": str(uuid.uuid4())[:8],
        "type": ntype,
        "law_name": law_name,
        "title": title,
        "body": body,
        "preview": preview,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False,
    })
    ndata["notifications"] = ndata["notifications"][:300]

def _fmt_date(s: str) -> str:
    s = str(s or "").replace("-", "")
    if len(s) == 8:
        return f"{s[:4]}.{s[4:6]}.{s[6:]}"
    return s or "-"


# ── 배치 스케줄러 ───────────────────────────────────────────────

def _parse_run_time(run_time: str, default_h: int = 2) -> tuple[int, int]:
    try:
        h, m = map(int, run_time.split(":"))
        return max(0, min(23, h)), max(0, min(59, m))
    except Exception:
        return default_h, 0

def _register_law_batch_job(run_time: str) -> None:
    h, m    = _parse_run_time(run_time, 2)
    trigger = CronTrigger(hour=h, minute=m, timezone="Asia/Seoul")
    job_id  = "batch_law_collect"
    if _scheduler.get_job(job_id):
        _scheduler.reschedule_job(job_id, trigger=trigger)
    else:
        _scheduler.add_job(_auto_run_law_batch, trigger, id=job_id,
                           misfire_grace_time=3600, coalesce=True)
    logger.info("법령 배치 스케줄: 매일 %02d:%02d", h, m)

def _register_prec_batch_job(run_time: str) -> None:
    h, m    = _parse_run_time(run_time, 3)
    trigger = CronTrigger(hour=h, minute=m, timezone="Asia/Seoul")
    job_id  = "batch_prec_collect"
    if _scheduler.get_job(job_id):
        _scheduler.reschedule_job(job_id, trigger=trigger)
    else:
        _scheduler.add_job(_auto_run_prec_batch, trigger, id=job_id,
                           misfire_grace_time=3600, coalesce=True)
    logger.info("판례 배치 스케줄: 매일 %02d:%02d", h, m)

async def _auto_run_law_batch() -> None:
    async with _law_lock:
        logger.info("자동 법령 배치 수집 시작")
        try:
            await _run_law_batch()
        except Exception as e:
            logger.error("자동 법령 배치 수집 실패: %s", e)

async def _auto_run_prec_batch() -> None:
    if _prec_lock.locked():
        logger.info("자동 판례 배치 스킵 — 이미 실행 중")
        return
    async with _prec_lock:
        logger.info("자동 판례 배치 수집 시작")
        try:
            await _run_prec_batch()
        except Exception as e:
            logger.error("자동 판례 배치 수집 실패: %s", e)


def _register_batchtest_job(run_time: str) -> None:
    h, m    = _parse_run_time(run_time, 2)
    trigger = CronTrigger(hour=h, minute=m, timezone="Asia/Seoul")
    job_id  = "batchtest_auto"
    if _scheduler.get_job(job_id):
        _scheduler.reschedule_job(job_id, trigger=trigger)
    else:
        _scheduler.add_job(_auto_run_batchtest, trigger, id=job_id,
                           misfire_grace_time=3600, coalesce=True)
    logger.info("배치 테스트 스케줄: 매일 %02d:%02d", h, m)

def _unregister_batchtest_job() -> None:
    if _scheduler.get_job("batchtest_auto"):
        _scheduler.remove_job("batchtest_auto")
        logger.info("배치 테스트 스케줄 해제")

async def _auto_run_batchtest() -> None:
    global _batch_test_cancel
    if _batch_test_cancel:
        logger.info("자동 배치 테스트 스킵 — 취소 상태")
        return
    config = _load_batchtest_config()
    if not config.get("enabled"):
        return
    req = BatchTestRequest(
        count=int(config.get("count", 0)),
        target=config.get("target", "prec"),
        repo=config.get("repo", "prec"),
        concurrent=int(config.get("concurrent", 1)),
    )
    logger.info("자동 배치 테스트 시작: target=%s, count=%d, repo=%s", req.target, req.count, req.repo)
    _batch_test_cancel = False
    try:
        response = await batchtest_run(req)
        async for _ in response.body_iterator:
            pass
        logger.info("자동 배치 테스트 완료")
    except Exception as e:
        logger.error("자동 배치 테스트 실패: %s", e)


async def _run_law_batch() -> dict:
    """법령 본문 일괄 수집 배치 — 시행예정 법령 API로 변경분만 확인"""
    from clients.law_client import search_eflaw

    config = _load_batch_law_config()
    states = _load_law_states()
    ndata  = _load_notifications()

    started       = datetime.now()
    laws_to_check = config.get("laws", [])
    total         = len(laws_to_check)
    changed_count = 0
    error_count   = 0
    results: list = []

    if not laws_to_check:
        logger.info("법령 배치: 수집 대상 없음")
        log_entry = {
            "id": str(uuid.uuid4())[:8],
            "started_at":  started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": 0,
            "total": 0, "changed": 0, "errors": 0, "results": [],
        }
        logs = _load_batch_law_logs()
        logs.insert(0, log_entry)
        _save_batch_law_logs(logs[:50])
        return log_entry

    # 최근 시행/변경된 법령 목록 조회 (오늘 기준)
    today_str = started.strftime("%Y%m%d")
    changed_law_names: set = set()
    try:
        ef_result = search_eflaw(date=today_str, display=200)
        for ef in ef_result.get("laws", []):
            changed_law_names.add(ef.get("법령명한글", ""))
        logger.info("시행예정/변경 법령 %d건 감지", len(changed_law_names))
    except Exception as e:
        logger.warning("시행예정 법령 조회 실패, 전체 스캔: %s", e)
        changed_law_names = None  # 실패 시 전체 스캔

    for law_entry in laws_to_check:
        law_name = law_entry["name"] if isinstance(law_entry, dict) else str(law_entry)
        state    = states.get(law_name, {})
        if not state.get("active", True):
            results.append({"name": law_name, "status": "비활성", "message": "폐지 비활성"})
            continue

        never_uploaded = not state.get("last_knowledge_upload")

        # 변경 목록에 없고 이미 업로드된 법령은 스킵
        if changed_law_names is not None and law_name not in changed_law_names and not never_uploaded:
            results.append({"name": law_name, "status": "success", "message": "변동없음(스킵)"})
            continue

        msgs: list[str] = []
        try:
            result  = search_law(query=law_name, display=10)
            laws    = result.get("laws", [])
            matched = next(
                (l for l in laws if l.get("법령명한글") == law_name),
                laws[0] if laws else None,
            )

            if not matched:
                if state.get("last_enforcement_date"):
                    existing_doc_ids = state.get("knowledge_doc_ids") or {}
                    if existing_doc_ids and KNOWLEDGE_LAW_REPO_ID:
                        try:
                            delete_documents(KNOWLEDGE_LAW_REPO_ID, list(existing_doc_ids.values()))
                            state["knowledge_doc_ids"] = {}
                        except KnowledgeApiError as ke:
                            logger.warning("폐지 법령 Knowledge 삭제 실패 (%s): %s", law_name, ke)
                    _push_notification(ndata, "폐지", law_name,
                        f"법령 폐지: {law_name}",
                        "법령 조회 결과 없음 — 폐지된 것으로 판단")
                    state["active"] = False
                    msgs.append("폐지감지")
                else:
                    msgs.append("조회결과없음")
                states[law_name] = state
                results.append({"name": law_name, "status": "폐지", "message": ", ".join(msgs)})
                continue

            new_ef         = str(matched.get("시행일자") or "")
            old_ef         = str(state.get("last_enforcement_date") or "")
            law_changed    = bool(old_ef and new_ef and new_ef != old_ef)
            never_uploaded = not state.get("last_knowledge_upload")

            if law_changed:
                _push_notification(ndata, "개정", law_name,
                    f"법령 개정: {law_name}",
                    f"시행일자 변경  {_fmt_date(old_ef)} → {_fmt_date(new_ef)}",
                    preview={"rows": [
                        {"label": "소관부처", "value": matched.get("소관부처명", "-")},
                        {"label": "시행일자", "value": _fmt_date(new_ef)},
                    ]})
                msgs.append(f"개정감지({_fmt_date(old_ef)}→{_fmt_date(new_ef)})")
                changed_count += 1

            state["last_enforcement_date"] = new_ef or old_ef
            state["law_id"] = str(matched.get("법령ID") or state.get("law_id", ""))

            if KNOWLEDGE_LAW_REPO_ID and (law_changed or never_uploaded):
                existing_doc_ids = state.get("knowledge_doc_ids") or {}
                if law_changed and existing_doc_ids:
                    try:
                        delete_documents(KNOWLEDGE_LAW_REPO_ID, list(existing_doc_ids.values()))
                        state["knowledge_doc_ids"] = {}
                    except KnowledgeApiError as ke:
                        logger.warning("기존 Knowledge 삭제 실패 (%s): %s", law_name, ke)

                law_id_str = state["law_id"]
                if law_id_str:
                    try:
                        law_detail   = get_law(law_id=law_id_str)
                        all_articles = law_detail.get("articles", [])
                        CHUNK        = 50
                        chunks = (
                            [all_articles[i:i+CHUNK] for i in range(0, len(all_articles), CHUNK)]
                            if all_articles else [[]]
                        )
                        new_doc_ids: dict = {}
                        chunk_uploaded    = 0
                        for chunk in chunks:
                            if not chunk:
                                continue
                            start  = chunk[0].get("조문번호", "")
                            end    = chunk[-1].get("조문번호", "")
                            suffix = f"_{start}-{end}조" if len(chunks) > 1 else ""
                            fname  = f"{law_name}{suffix}.md"
                            md     = law_to_markdown(law_detail, articles=chunk)
                            try:
                                res    = ingest(KNOWLEDGE_LAW_REPO_ID, md, fname,
                                                metadata={"category": "법령", "tags": [law_name]})
                                doc_id = (res or {}).get("datasource_file_id")
                                if doc_id:
                                    new_doc_ids[fname] = doc_id
                                chunk_uploaded += 1
                            except KnowledgeDuplicateError:
                                chunk_uploaded += 1
                        if chunk_uploaded:
                            state["knowledge_doc_ids"]     = new_doc_ids
                            state["last_knowledge_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            msgs.append(f"Knowledge {chunk_uploaded}청크 업로드")
                            if never_uploaded:
                                changed_count += 1
                    except KnowledgeApiError as ke:
                        msgs.append(f"업로드실패:{str(ke)[:40]}")
                        error_count += 1
                        _push_notification(ndata, "실패", law_name,
                            f"Knowledge 업로드 실패: {law_name}", str(ke)[:100])

            if not msgs:
                msgs.append("변동없음")

            states[law_name] = state
            results.append({"name": law_name, "status": "success", "message": ", ".join(msgs)})

        except LawApiError as e:
            error_count += 1
            states[law_name] = state
            results.append({"name": law_name, "status": "error", "message": str(e)[:100]})
            logger.warning("법령 배치 수집 실패 (%s): %s", law_name, e)
        except Exception as e:
            error_count += 1
            states[law_name] = state
            results.append({"name": law_name, "status": "error", "message": f"오류: {str(e)[:80]}"})
            logger.error("법령 배치 예기치 않은 오류 (%s): %s", law_name, e, exc_info=True)
        finally:
            _save_law_states(states)

    _save_law_states(states)
    _save_notifications(ndata)

    finished  = datetime.now()
    elapsed   = int((finished - started).total_seconds())
    log_entry = {
        "id":          str(uuid.uuid4())[:8],
        "started_at":  started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "total":       total,
        "changed":     changed_count,
        "errors":      error_count,
        "results":     results,
    }
    logs = _load_batch_law_logs()
    logs.insert(0, log_entry)
    _save_batch_law_logs(logs[:50])

    logger.info("법령 배치 완료: 전체 %d건, 변동 %d건, 오류 %d건, %d초 소요",
                total, changed_count, error_count, elapsed)
    return log_entry


async def _run_prec_batch() -> dict:
    """판례 일괄 수집 배치 — 자체 법령 목록 사용"""
    config = _load_batch_prec_config()
    states = _load_prec_states()
    ndata  = _load_notifications()

    started       = datetime.now()
    laws_to_check = config.get("laws", [])
    total         = len(laws_to_check)
    changed_count = 0
    error_count   = 0
    results: list = []

    if not laws_to_check:
        logger.info("판례 배치: 수집 대상 없음")
        log_entry = {
            "id": str(uuid.uuid4())[:8],
            "started_at":  started.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": started.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": 0,
            "total": 0, "changed": 0, "errors": 0, "results": [],
        }
        logs = _load_batch_prec_logs()
        logs.insert(0, log_entry)
        _save_batch_prec_logs(logs[:50])
        return log_entry

    BATCH_UPLOAD_SIZE = 10
    batch_count = 0

    for law_entry in laws_to_check:
        law_name = law_entry["name"] if isinstance(law_entry, dict) else str(law_entry)
        state    = states.get(law_name, {})
        msgs: list[str] = []

        try:
            # 1페이지만 조회해서 total_cnt 비교
            first_page = search_prec(jo=law_name, display=100, page=1)
            new_prec_cnt = int(first_page.get("total_cnt") or 0)
            old_prec_cnt = state.get("last_prec_count")

            # total_cnt 변동 없고 이미 업로드한 적 있으면 스킵
            if old_prec_cnt is not None and new_prec_cnt == int(old_prec_cnt) and state.get("uploaded_prec_ids"):
                state["last_prec_count"] = new_prec_cnt
                states[law_name] = state
                results.append({"name": law_name, "status": "success", "message": "변동없음"})
                continue

            # 변동 있으면 전체 목록 수집
            PREC_DISPLAY = 100
            all_precs: list = list(first_page.get("precs", []))
            prec_page = 2

            while len(all_precs) < new_prec_cnt:
                pr = search_prec(jo=law_name, display=PREC_DISPLAY, page=prec_page)
                batch_precs = pr.get("precs", [])
                all_precs.extend(batch_precs)
                if len(batch_precs) < PREC_DISPLAY:
                    break
                prec_page += 1
            if old_prec_cnt is not None and new_prec_cnt > int(old_prec_cnt):
                diff = new_prec_cnt - int(old_prec_cnt)
                _push_notification(ndata, "판례", law_name,
                    f"판례 신규 추가: {law_name}",
                    f"{diff}건 신규 추가 (누적 {new_prec_cnt:,}건)")
                msgs.append(f"판례+{diff}건")

            uploaded_ids: set = set(state.get("uploaded_prec_ids") or [])
            prec_uploaded = 0
            # in_flight: doc_id → (prec_id, upload_time)
            in_flight: dict[str, tuple] = {}
            MAX_IN_FLIGHT = 10
            POLL_INTERVAL = 10
            DOC_TIMEOUT = 300  # 5분

            if KNOWLEDGE_PREC_REPO_ID:
                prec_iter = iter(all_precs)
                done_feeding = False

                while not done_feeding or in_flight:
                    if _prec_batch_cancel:
                        msgs.append("중지됨")
                        break

                    # 빈 자리만큼 업로드
                    while len(in_flight) < MAX_IN_FLIGHT and not done_feeding:
                        p = next(prec_iter, None)
                        if p is None:
                            done_feeding = True
                            break
                        pid = str(p.get("판례정보일련번호") or p.get("판례일련번호") or "")
                        if not pid or pid in uploaded_ids:
                            continue
                        if _prec_batch_cancel:
                            msgs.append("중지됨")
                            done_feeding = True
                            break
                        try:
                            prec_detail = await asyncio.to_thread(get_prec, prec_id=pid)
                            md          = prec_to_markdown(prec_detail)
                            case_name   = prec_detail.get("case_name") or p.get("사건명", pid)
                            case_no     = prec_detail.get("case_no", "")
                            court       = prec_detail.get("court", "")
                            date_val    = prec_detail.get("date", "")
                            id_header   = f"사건번호: {case_no}\n판례ID: {pid}\n법원명: {court}\n선고일자: {date_val}\n사건명: {case_name}\n\n---\n\n"
                            result = await asyncio.to_thread(
                                ingest, KNOWLEDGE_PREC_REPO_ID, id_header + md, f"{pid}_{case_name}.md",
                                {"category": "판례", "case_no": case_no, "prec_id": pid,
                                 "court": court, "date": date_val, "tags": [law_name, case_name]})
                            doc_id = result.get("id") or result.get("document_id", "")
                            if doc_id:
                                in_flight[doc_id] = (pid, datetime.now())
                            uploaded_ids.add(pid)
                            prec_uploaded += 1
                            batch_count += 1
                        except KnowledgeDuplicateError:
                            uploaded_ids.add(pid)
                        except KnowledgeApiError as ke:
                            logger.warning("판례 Knowledge 업로드 실패 (%s): %s", pid, ke)
                        except Exception as e:
                            uploaded_ids.add(pid)
                            logger.warning("판례 상세 조회 실패 스킵 (%s): %s", pid, e)

                    # in_flight 중 완료/타임아웃 제거
                    if in_flight:
                        completed = []
                        now = datetime.now()
                        for doc_id, (pid, upload_time) in in_flight.items():
                            elapsed = (now - upload_time).total_seconds()
                            if elapsed > DOC_TIMEOUT:
                                completed.append(doc_id)
                                logger.warning("임베딩 타임아웃 (%.0f초): %s", elapsed, pid)
                                continue
                            try:
                                doc = await asyncio.to_thread(get_document_status, KNOWLEDGE_PREC_REPO_ID, doc_id)
                                status = doc.get("status", "")
                                logger.debug("문서 상태: %s → %s (%.0f초 경과)", pid, status, elapsed)
                                if status == "embedded":
                                    completed.append(doc_id)
                                elif status == "failed":
                                    completed.append(doc_id)
                                    logger.warning("임베딩 실패: %s", pid)
                            except Exception:
                                pass
                        for doc_id in completed:
                            del in_flight[doc_id]
                        if completed:
                            logger.info("임베딩 완료 %d건, 대기 중 %d건 (현재: %s)", len(completed), len(in_flight), law_name)

                    # 상태 저장
                    if batch_count >= BATCH_UPLOAD_SIZE:
                        state["uploaded_prec_ids"] = list(uploaded_ids)
                        _save_prec_states(states)
                        logger.info("배치 상태 저장: 누적 %d건 (현재: %s)", prec_uploaded, law_name)
                        batch_count = 0

                    # 아직 처리 중이면 대기
                    if in_flight and not done_feeding:
                        await asyncio.sleep(POLL_INTERVAL)

            if prec_uploaded:
                state["uploaded_prec_ids"]          = list(uploaded_ids)
                state["last_prec_knowledge_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msgs.append(f"Knowledge {prec_uploaded}건 업로드")
                changed_count += 1

            state["last_prec_count"] = new_prec_cnt
            if not msgs:
                msgs.append("변동없음")

            states[law_name] = state
            results.append({"name": law_name, "status": "success", "message": ", ".join(msgs)})

        except LawApiError as e:
            error_count += 1
            states[law_name] = state
            results.append({"name": law_name, "status": "error", "message": str(e)[:100]})
            logger.warning("판례 배치 수집 실패 (%s): %s", law_name, e)
        except Exception as e:
            error_count += 1
            states[law_name] = state
            results.append({"name": law_name, "status": "error", "message": f"오류: {str(e)[:80]}"})
            logger.error("판례 배치 예기치 않은 오류 (%s): %s", law_name, e, exc_info=True)
        finally:
            _save_prec_states(states)

    _save_prec_states(states)
    _save_notifications(ndata)

    finished  = datetime.now()
    elapsed   = int((finished - started).total_seconds())
    log_entry = {
        "id":          str(uuid.uuid4())[:8],
        "started_at":  started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "total":       total,
        "changed":     changed_count,
        "errors":      error_count,
        "results":     results,
    }
    logs = _load_batch_prec_logs()
    logs.insert(0, log_entry)
    _save_batch_prec_logs(logs[:50])

    logger.info("판례 배치 완료: 전체 %d건, 신규업로드 %d건, 오류 %d건, %d초 소요",
                total, changed_count, error_count, elapsed)
    return log_entry


@asynccontextmanager
async def lifespan(app_: FastAPI):
    # _register_law_batch_job(_load_batch_law_config().get("run_time", "02:00"))
    # _register_prec_batch_job(_load_batch_prec_config().get("run_time", "03:00"))
    bt_cfg = _load_batchtest_config()
    if bt_cfg.get("enabled"):
        _register_batchtest_job(bt_cfg.get("run_time", "02:00"))
    if PHARMA_ENABLED:
        pharma_init_db()
        _scheduler.add_job(sync_emails_job,   "interval", minutes=PHARMA_CHECK_INTERVAL_MIN,
                           id="pharma_email_sync",    coalesce=True, misfire_grace_time=300)
        _scheduler.add_job(check_overdue_job, "interval", hours=1,
                           id="pharma_overdue_check", coalesce=True, misfire_grace_time=300)
        from config import PUBSUB_PROJECT_ID
        if PUBSUB_PROJECT_ID:
            _scheduler.add_job(pubsub_pull_job,    "interval", seconds=30,
                               id="pharma_pubsub_pull",   coalesce=True, misfire_grace_time=60)
            _scheduler.add_job(watch_renewal_job,  "interval", hours=6,
                               id="pharma_watch_renewal", coalesce=True, misfire_grace_time=3600)
    _scheduler.start()
    logger.info("APScheduler 시작 — 등록 job: %d개", len(_scheduler.get_jobs()))
    yield
    _scheduler.shutdown(wait=False)
    logger.info("APScheduler 종료")


app = FastAPI(title="Agent Chat", lifespan=lifespan)
if PHARMA_ENABLED:
    app.include_router(pharma_router)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── 요청 모델 ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)

class BatchRunTimeUpdate(BaseModel):
    run_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

class BatchLawAdd(BaseModel):
    names: list[str]


# ── 기본 라우트 ─────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    content = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "agent_configured": bool(AGENT_API_KEY),
        "agent_id": AGENT_ID,
        "summarize_enabled": bool(SUMMARIZE_AGENT_ID and SUMMARIZE_API_KEY),
    }


# ── 채팅 ────────────────────────────────────────────────────────

@app.post("/api/summarize")
async def summarize(req: SummarizeRequest):
    logger.info("판례 요약 요청 (%d자)", len(req.text))
    try:
        result = invoke_agent(req.text.strip(), agent_id=SUMMARIZE_AGENT_ID, api_key=SUMMARIZE_API_KEY)
        return {"summary": result["content"]}
    except AgentApiError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=str(e)) from e


@app.post("/api/chat")
async def chat(req: ChatRequest):
    logger.info("채팅 요청 (invoke): %s", req.message[:100])
    try:
        result = invoke_agent(req.message.strip())
        logger.info("채팅 완료 run_id=%s", result.get("run_id"))
        return {"content": result["content"], "run_id": result.get("run_id")}
    except AgentApiError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e


_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

def _stream_response(message: str, agent_id: str | None = None, api_key: str | None = None) -> StreamingResponse:
    def event_generator():
        try:
            for token in stream_agent_tokens(message, agent_id=agent_id, api_key=api_key):
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except AgentApiError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    logger.info("채팅 요청 (stream): %s", req.message[:100])
    return _stream_response(req.message.strip())


@app.post("/api/lawprec/chat/stream")
async def lawprec_chat_stream(req: ChatRequest):
    logger.info("법률판례질의 요청 (stream): %s", req.message[:100])
    if not LAW_PREC_AGENT_ID or not LAW_PREC_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="LAW_PREC_AGENT_ID / LAW_PREC_AGENT_API_KEY가 설정되지 않았습니다.")
    return _stream_response(req.message.strip(), LAW_PREC_AGENT_ID, LAW_PREC_AGENT_API_KEY)


@app.post("/api/lawprec/invoke")
async def lawprec_invoke(req: ChatRequest):
    message = req.message.strip()
    logger.info("법률판례질의 요청 (invoke): %s", message[:100])

    if not LAW_PREC_AGENT_ID or not LAW_PREC_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="LAW_PREC_AGENT_ID / LAW_PREC_AGENT_API_KEY가 설정되지 않았습니다.")

    try:
        result = await asyncio.to_thread(
            invoke_agent, message,
            agent_id=LAW_PREC_AGENT_ID, api_key=LAW_PREC_AGENT_API_KEY,
        )
        return {"content": result.get("content", "")}
    except AgentApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── 키워드 검색 테스트: Agent 키워드 추출 → Law API ───────────

@app.post("/api/keyword/extract")
async def keyword_extract(req: ChatRequest):
    """키워드 추출 에이전트 호출 (invoke)"""
    message = req.message.strip()
    if not LAW_KEYWORD_AGENT_ID or not LAW_KEYWORD_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="LAW_KEYWORD_AGENT_ID가 설정되지 않았습니다.")
    try:
        result = await asyncio.to_thread(
            invoke_agent, message,
            agent_id=LAW_KEYWORD_AGENT_ID, api_key=LAW_KEYWORD_AGENT_API_KEY,
        )
        return {"content": result.get("content", "")}
    except AgentApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


async def _merge_prec_searches(*search_kwargs: dict) -> list[dict]:
    results = await asyncio.gather(
        *(asyncio.to_thread(search_prec, **kw) for kw in search_kwargs),
        return_exceptions=True,
    )
    seen, merged = set(), []
    for result in results:
        if isinstance(result, Exception):
            continue
        for p in result.get("precs", []):
            pid = str(p.get("판례정보일련번호") or p.get("판례일련번호") or "")
            if pid and pid not in seen:
                seen.add(pid)
                merged.append(p)
    return merged


@app.get("/api/keyword/search")
async def keyword_search(q: str, display: int = 20):
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요.")
    try:
        merged = await _merge_prec_searches(
            {"query": q, "search": 1, "display": display},
            {"query": q, "search": 2, "display": display},
        )
        return {"precs": merged, "total": len(merged)}
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/analysis/prec/search")
async def analysis_prec_search(q: str, display: int = 20):
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요.")
    try:
        merged = await _merge_prec_searches(
            {"query": q, "display": display},
            {"jo": q, "display": display},
        )
        return {"precs": merged, "total": len(merged)}
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 법령 / 판례 ─────────────────────────────────────────────────

@app.get("/api/law/search")
async def law_search(q: str = "", page: int = 1, display: int = 15, search: int | None = None):
    logger.info("법령 검색: %s (search=%s)", q or "(전체)", search)
    try:
        return search_law(query=q or None, page=page, display=display, search=search)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/law/article")
async def law_article(law_name: str, jo: int, jo_sub: int = 0):
    logger.info("조문 조회: %s 제%d조", law_name, jo)
    try:
        result = search_law(query=law_name, display=10)
        laws   = result["laws"]
        if not laws:
            raise HTTPException(status_code=404, detail=f"'{law_name}' 법령을 찾을 수 없습니다.")

        target = (
            next((l for l in laws if l.get("법령명한글") == law_name), None)
            or next((l for l in laws if l.get("법령명한글", "").startswith(law_name)), None)
            or laws[0]
        )

        law_id          = str(target["법령ID"])
        law_full_name   = target.get("법령명한글", law_name)
        logger.info("  매칭된 법령: %s (ID=%s)", law_full_name, law_id)

        detail = get_law(law_id=law_id, jo=format_jo(jo, jo_sub))
        detail["searched_law_name"] = law_full_name
        detail["searched_jo"]       = jo

        if not detail.get("articles"):
            raise HTTPException(status_code=404,
                detail=f"'{law_full_name}' 제{jo}조를 찾을 수 없습니다.")

        return detail
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/law/{law_id}")
async def law_detail(law_id: str):
    logger.info("법령 조회: %s", law_id)
    try:
        return get_law(law_id=law_id)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/prec/search")
async def prec_search(q: str = "", page: int = 1, display: int = 15, search: int | None = None):
    logger.info("판례 검색: %s (search=%s)", q or "(전체)", search)
    try:
        return search_prec(query=q or None, page=page, display=display, search=search)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/prec/{prec_id}")
async def prec_detail(prec_id: str):
    logger.info("판례 조회: %s", prec_id)
    try:
        return get_prec(prec_id=prec_id)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 알림 ────────────────────────────────────────────────────────

@app.get("/api/notifications")
async def notifications_list():
    return _load_notifications()


@app.post("/api/notifications/{notif_id}/read", status_code=204)
async def notification_mark_read(notif_id: str):
    ndata = _load_notifications()
    for n in ndata["notifications"]:
        if n["id"] == notif_id:
            n["read"] = True
            break
    _save_notifications(ndata)


@app.post("/api/notifications/read-all", status_code=204)
async def notification_mark_all_read():
    ndata = _load_notifications()
    for n in ndata["notifications"]:
        n["read"] = True
    _save_notifications(ndata)


@app.delete("/api/notifications/{notif_id}", status_code=204)
async def notification_delete(notif_id: str):
    ndata = _load_notifications()
    ndata["notifications"] = [n for n in ndata["notifications"] if n["id"] != notif_id]
    _save_notifications(ndata)


@app.delete("/api/notifications", status_code=204)
async def notification_delete_all():
    _save_notifications({"notifications": []})


# ── 배치 관리 — 법령 ───────────────────────────────────────────

def _law_config_with_state() -> dict:
    config = _load_batch_law_config()
    states = _load_law_states()
    laws   = []
    for entry in config.get("laws", []):
        name  = entry["name"] if isinstance(entry, dict) else str(entry)
        state = states.get(name, {})
        laws.append({
            "name":                  name,
            "added_at":              entry.get("added_at") if isinstance(entry, dict) else None,
            "last_enforcement_date": state.get("last_enforcement_date"),
            "last_knowledge_upload": state.get("last_knowledge_upload"),
            "active":                state.get("active", True),
        })
    return {"run_time": config.get("run_time", "02:00"), "laws": laws}

@app.get("/api/batch/law/config")
async def batch_law_config_get():
    return _law_config_with_state()

@app.put("/api/batch/law/config/run-time")
async def batch_law_run_time_update(body: BatchRunTimeUpdate):
    config = _load_batch_law_config()
    config["run_time"] = body.run_time
    _save_batch_law_config(config)
    _register_law_batch_job(body.run_time)
    return {"run_time": body.run_time}

@app.post("/api/batch/law/laws", status_code=201)
async def batch_law_laws_add(body: BatchLawAdd):
    config   = _load_batch_law_config()
    existing = {(e["name"] if isinstance(e, dict) else e) for e in config.get("laws", [])}
    added, now_str = [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for name in body.names:
        name = name.strip()
        if not name or name in existing:
            continue
        config.setdefault("laws", []).append({"name": name, "added_at": now_str})
        existing.add(name)
        added.append(name)
    _save_batch_law_config(config)
    return {"added": added, "total": len(config["laws"])}

@app.delete("/api/batch/law/laws/{law_name}", status_code=204)
async def batch_law_laws_delete(law_name: str):
    config = _load_batch_law_config()
    config["laws"] = [e for e in config.get("laws", [])
                      if (e["name"] if isinstance(e, dict) else e) != law_name]
    _save_batch_law_config(config)

@app.post("/api/batch/law/laws/load-defaults", status_code=201)
async def batch_law_laws_load_defaults():
    try:
        result = search_law(org="1492000", display=200)
        laws   = result.get("laws", [])
    except LawApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    config   = _load_batch_law_config()
    existing = {(e["name"] if isinstance(e, dict) else e) for e in config.get("laws", [])}
    added, now_str = [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for l in laws:
        name = l.get("법령명한글") or l.get("법령명")
        if not name or name in existing:
            continue
        config.setdefault("laws", []).append({"name": name, "added_at": now_str})
        existing.add(name)
        added.append(name)
    _save_batch_law_config(config)
    return {"added_count": len(added), "total": len(config["laws"]), "added": added}

@app.post("/api/batch/law/run")
async def batch_law_run_manual():
    async with _law_lock:
        try:
            return await _run_law_batch()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

@app.get("/api/batch/law/logs")
async def batch_law_logs_get():
    return {"logs": _load_batch_law_logs()}


# ── 배치 관리 — 판례 ───────────────────────────────────────────

def _prec_config_with_state() -> dict:
    """판례 배치 설정: 자체 법령 목록 + prec_states 상태"""
    prec_config = _load_batch_prec_config()
    states      = _load_prec_states()
    laws = []
    for entry in prec_config.get("laws", []):
        name  = entry["name"] if isinstance(entry, dict) else str(entry)
        state = states.get(name, {})
        laws.append({
            "name":                       name,
            "last_prec_count":            state.get("last_prec_count"),
            "last_prec_knowledge_upload": state.get("last_prec_knowledge_upload"),
            "uploaded_count":             len(state.get("uploaded_prec_ids") or []),
        })
    return {"run_time": prec_config.get("run_time", "03:00"), "laws": laws}

@app.get("/api/batch/prec/config")
async def batch_prec_config_get():
    return _prec_config_with_state()

@app.put("/api/batch/prec/config/run-time")
async def batch_prec_run_time_update(body: BatchRunTimeUpdate):
    config = _load_batch_prec_config()
    config["run_time"] = body.run_time
    _save_batch_prec_config(config)
    _register_prec_batch_job(body.run_time)
    return {"run_time": body.run_time}

@app.post("/api/batch/prec/laws", status_code=201)
async def batch_prec_laws_add(body: BatchLawAdd):
    config   = _load_batch_prec_config()
    existing = {(e["name"] if isinstance(e, dict) else e) for e in config.get("laws", [])}
    added, now_str = [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for name in body.names:
        name = name.strip()
        if not name or name in existing:
            continue
        config.setdefault("laws", []).append({"name": name, "added_at": now_str})
        existing.add(name)
        added.append(name)
    _save_batch_prec_config(config)
    return {"added": added, "total": len(config["laws"])}

@app.delete("/api/batch/prec/laws/{law_name}", status_code=204)
async def batch_prec_laws_delete(law_name: str):
    config = _load_batch_prec_config()
    config["laws"] = [e for e in config.get("laws", [])
                      if (e["name"] if isinstance(e, dict) else e) != law_name]
    _save_batch_prec_config(config)

async def _background_prec_batch():
    global _prec_batch_cancel
    _prec_batch_cancel = False
    async with _prec_lock:
        try:
            await _run_prec_batch()
        except Exception as e:
            logger.error("판례 배치 백그라운드 실패: %s", e)

@app.post("/api/batch/prec/run")
async def batch_prec_run_manual():
    if _prec_lock.locked():
        raise HTTPException(status_code=409, detail="이미 실행 중입니다.")
    asyncio.create_task(_background_prec_batch())
    return {"status": "started"}

@app.post("/api/batch/prec/cancel")
async def batch_prec_cancel():
    global _prec_batch_cancel
    _prec_batch_cancel = True
    return {"status": "cancel_requested"}

@app.get("/api/batch/prec/status")
async def batch_prec_status():
    return {"running": _prec_lock.locked()}

@app.get("/api/batch/prec/logs")
async def batch_prec_logs_get():
    return {"logs": _load_batch_prec_logs()}


# ── Knowledge 관리 ─────────────────────────────────────────────

@app.delete("/api/knowledge/hard-delete/{datasource_id}", status_code=200)
async def knowledge_hard_delete(datasource_id: str):
    try:
        await asyncio.to_thread(hard_delete_datasource, datasource_id)
        return {"status": "deleted", "datasource_id": datasource_id}
    except KnowledgeApiError as e:
        raise HTTPException(status_code=e.status_code or 500, detail=str(e)) from e


# ── RAG 테스트 ──────────────────────────────────────────────────

class TestCollectRequest(BaseModel):
    law_name: str

@app.get("/api/test/laws")
async def test_laws_get():
    config = _load_batch_law_config()
    return {
        "laws": [
            (e["name"] if isinstance(e, dict) else str(e))
            for e in config.get("laws", [])
        ]
    }


@app.post("/api/test/collect/law")
async def test_collect_law(req: TestCollectRequest):
    law_name = req.law_name.strip()
    logger.info("RAG 테스트 법령 수집: %s", law_name)

    async def gen():
        def emit(data):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            yield emit({"step": "fetch", "status": "start", "message": f"'{law_name}' 법령 API 조회 중..."})
            result  = await asyncio.to_thread(search_law, query=law_name, display=10)
            laws    = result.get("laws", [])
            matched = next((l for l in laws if l.get("법령명한글") == law_name), laws[0] if laws else None)
            if not matched:
                yield emit({"step": "fetch", "status": "error", "message": f"'{law_name}' 법령을 찾을 수 없습니다"})
                return
            law_id     = str(matched.get("법령ID") or "")
            law_detail = await asyncio.to_thread(get_law, law_id=law_id)
            md         = law_to_markdown(law_detail)
            article_cnt = len(law_detail.get("articles", []))
            yield emit({"step": "fetch", "status": "done", "message": f"조문 {article_cnt}개 수집 완료"})

            yield emit({"step": "summarize", "status": "start", "message": "에이전트 요약 중..."})
            if not LAW_PREC_TEST_AGENT_ID or not LAW_PREC_TEST_AGENT_API_KEY:
                yield emit({"step": "summarize", "status": "error", "message": "LAW_PREC_TEST_AGENT_ID / LAW_PREC_TEST_AGENT_API_KEY 미설정"})
                return
            resp    = await asyncio.to_thread(invoke_agent, f"다음 법령을 아래 형식으로 500자 이내로 요약하세요. 형식 외 텍스트는 출력하지 마세요.\n\n1. 법령 목적: (1문장)\n2. 핵심 의무·권리: (2문장)\n3. 주요 제재·벌칙: (1문장)\n4. 적용 대상: (1문장)\n\n[법령]\n{md[:8000]}",
                                              agent_id=LAW_PREC_TEST_AGENT_ID, api_key=LAW_PREC_TEST_AGENT_API_KEY)
            summary = resp.get("content", "")
            if not summary:
                yield emit({"step": "summarize", "status": "error", "message": "에이전트 요약 결과 없음"})
                return
            yield emit({"step": "summarize", "status": "done", "message": f"요약 완료 ({len(summary)}자)"})

            yield emit({"step": "upload", "status": "start", "message": "Knowledge 업로드 중..."})
            if not KNOWLEDGE_SUMM_REPO_ID:
                yield emit({"step": "upload", "status": "error", "message": "KNOWLEDGE_SUMM_REPO_ID 미설정"})
                return
            file_name = f"{law_name}_요약.md"
            id_header = f"법령명: {law_name}\n법령ID: {law_id}\n\n---\n\n"
            try:
                await asyncio.to_thread(ingest, KNOWLEDGE_SUMM_REPO_ID, id_header + summary, file_name,
                                        {"category": "법령요약", "law_id": law_id, "law_name": law_name, "tags": [law_name]})
                yield emit({"step": "upload", "status": "done", "message": f"업로드 완료: {file_name}"})
            except KnowledgeDuplicateError:
                yield emit({"step": "upload", "status": "done", "message": "이미 업로드됨 (중복 스킵)"})
            except Exception as e:
                yield emit({"step": "upload", "status": "error",
                            "message": f"업로드 실패 [{type(e).__name__}] {str(e)[:200]}"})

        except Exception as e:
            yield emit({"step": "error", "status": "error",
                        "message": f"실패 [{type(e).__name__}] {str(e)[:200]}"})
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.post("/api/test/collect/prec")
async def test_collect_prec(req: TestCollectRequest):
    law_name = req.law_name.strip()
    logger.info("RAG 테스트 판례 수집: %s", law_name)

    async def gen():
        def emit(data):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            # ── 1단계: 전체 목록 수집 (JO=참조법령명, 100건씩 페이지네이션) ──
            _DISPLAY = 100
            yield emit({"step": "fetch", "status": "start",
                        "message": f"'{law_name}' 참조 판례 검색 중..."})
            first = await asyncio.to_thread(search_prec, jo=law_name, display=_DISPLAY, page=1)
            total = int(first.get("total_cnt") or 0)
            all_precs = first.get("precs", [])
            if not all_precs:
                yield emit({"step": "fetch", "status": "error", "message": "참조 판례가 없습니다"})
                return
            yield emit({"step": "fetch", "status": "start",
                        "message": f"1페이지: {len(all_precs)}건 수신 (전체 {total:,}건)"})

            page = 2
            while len(all_precs) < total:
                pr    = await asyncio.to_thread(search_prec, jo=law_name, display=_DISPLAY, page=page)
                batch = pr.get("precs", [])
                yield emit({"step": "fetch", "status": "start",
                            "message": f"{page}페이지: {len(batch)}건 → 누계 {len(all_precs) + len(batch):,}/{total:,}건"})
                if not batch:
                    break
                all_precs.extend(batch)
                page += 1

            yield emit({"step": "fetch", "status": "done",
                        "message": f"총 {len(all_precs):,}건 목록 수집 완료"})

            if not LAW_PREC_TEST_AGENT_ID or not LAW_PREC_TEST_AGENT_API_KEY:
                yield emit({"step": "summarize", "status": "error", "message": "LAW_PREC_TEST_AGENT_ID / LAW_PREC_TEST_AGENT_API_KEY 미설정"})
                return
            if not KNOWLEDGE_SUMM_REPO_ID:
                yield emit({"step": "upload", "status": "error", "message": "KNOWLEDGE_SUMM_REPO_ID 미설정"})
                return

            # ── 2단계: 각 판례 요약·업로드 ──
            n = len(all_precs)
            uploaded = skipped = failed = 0
            for i, p in enumerate(all_precs):
                prec_id   = str(p.get("판례정보일련번호") or p.get("판례일련번호") or "")
                case_name = p.get("사건명", prec_id)
                yield emit({"step": "summarize", "status": "start",
                            "message": f"[{i+1}/{n}] {case_name} 요약 중..."})
                try:
                    detail  = await asyncio.to_thread(get_prec, prec_id=prec_id)
                    md      = prec_to_markdown(detail)
                    resp    = await asyncio.to_thread(
                        invoke_agent,
                        f"다음 판례를 아래 형식으로 500자 이내로 요약하세요. 형식 외 텍스트는 출력하지 마세요.\n\n1. 사건 핵심 사실: (2문장)\n2. 법적 쟁점: (1문장)\n3. 법원의 판단: (2문장)\n4. 법리 기준: (1문장)\n5. 결론 및 의미: (1문장)\n\n[판례]\n{md[:6000]}",
                        agent_id=LAW_PREC_TEST_AGENT_ID, api_key=LAW_PREC_TEST_AGENT_API_KEY,
                    )
                    summary = resp.get("content", "")
                    if not summary:
                        failed += 1
                        yield emit({"step": "summarize", "status": "error",
                                    "message": f"[{i+1}/{n}] {case_name} 요약 결과 없음"})
                        continue
                    file_name   = f"{prec_id}_{case_name}_요약.md"
                    case_no_val = detail.get("case_no", "")
                    id_header   = f"사건명: {case_name}\n사건번호: {case_no_val}\n판례ID: {prec_id}\n\n---\n\n"
                    await asyncio.to_thread(ingest, KNOWLEDGE_SUMM_REPO_ID, id_header + summary, file_name,
                                            {"category": "판례요약", "prec_id": prec_id, "case_no": case_no_val,
                                             "tags": [law_name, case_name]})
                    uploaded += 1
                    yield emit({"step": "upload", "status": "done",
                                "message": f"[{i+1}/{n}] {case_name} 업로드"})
                except KnowledgeDuplicateError:
                    skipped += 1
                    yield emit({"step": "upload", "status": "done",
                                "message": f"[{i+1}/{n}] {case_name} 중복 스킵"})
                except Exception as e:
                    failed += 1
                    yield emit({"step": "error", "status": "error",
                                "message": f"[{i+1}/{n}] {case_name} 실패 [{type(e).__name__}] {str(e)[:200]}"})

            yield emit({"step": "done", "status": "done",
                        "message": f"완료 — 업로드 {uploaded:,}건, 중복 {skipped:,}건, 실패 {failed:,}건"})

        except LawApiError as e:
            yield emit({"step": "error", "status": "error", "message": f"판례 API 오류: {str(e)[:120]}"})
        except Exception as e:
            yield emit({"step": "error", "status": "error", "message": f"오류: {str(e)[:120]}"})
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.post("/api/test/chat/stream")
async def test_chat_stream(req: ChatRequest):
    logger.info("RAG 테스트 질의: %s", req.message[:100])
    if not LAW_PREC_TEST_AGENT_ID or not LAW_PREC_TEST_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="LAW_PREC_TEST_AGENT_ID / LAW_PREC_TEST_AGENT_API_KEY가 설정되지 않았습니다.")
    return _stream_response(req.message.strip(), LAW_PREC_TEST_AGENT_ID, LAW_PREC_TEST_AGENT_API_KEY)


# ── 배치 적재 테스트 ──────────────────────────────────────────────

BATCH_TEST_RESULTS_FILE = _DATA_DIR / "batch_test_results.json"
_batch_test_cancel = False

def _load_batch_test_results():
    return _load_json(BATCH_TEST_RESULTS_FILE, [])

def _save_batch_test_results(d):
    _save_json(BATCH_TEST_RESULTS_FILE, d)


class BatchTestRequest(BaseModel):
    count: int = Field(..., ge=0, le=5000)  # 0 = 전체 (제한 없음)
    target: str = Field(default="law")  # "law" or "prec"
    repo: str = Field(default="law")    # "law", "prec", "summ"
    concurrent: int = Field(default=1, ge=1, le=20)
    keyword: str = Field(default="근로기준법")  # 판례 검색 시 참조 법령명


@app.get("/api/batchtest/schedule")
async def batchtest_schedule_get():
    return _load_batchtest_config()

@app.post("/api/batchtest/schedule")
async def batchtest_schedule_set(body: dict):
    config = _load_batchtest_config()
    config.update({k: body[k] for k in ("enabled", "run_time", "target", "repo", "count", "concurrent") if k in body})
    _save_batchtest_config(config)
    if config.get("enabled"):
        _register_batchtest_job(config["run_time"])
    else:
        _unregister_batchtest_job()
    return config


@app.get("/api/batchtest/results")
async def batchtest_results_get():
    return {"results": _load_batch_test_results()}


@app.delete("/api/batchtest/results", status_code=204)
async def batchtest_results_clear():
    _save_batch_test_results([])


@app.post("/api/batchtest/cancel")
async def batchtest_cancel():
    global _batch_test_cancel
    _batch_test_cancel = True
    return {"status": "cancel_requested"}


@app.post("/api/batchtest/run")
async def batchtest_run(req: BatchTestRequest):
    global _batch_test_cancel
    _batch_test_cancel = False

    repo_map = {"law": KNOWLEDGE_LAW_REPO_ID, "prec": KNOWLEDGE_PREC_REPO_ID, "summ": KNOWLEDGE_SUMM_REPO_ID}
    repo_id = repo_map.get(req.repo, "")
    if not repo_id:
        raise HTTPException(status_code=400, detail=f"KNOWLEDGE_{req.repo.upper()}_REPO_ID 미설정")

    logger.info("배치 적재 테스트: target=%s, count=%d, repo=%s, concurrent=%d",
                req.target, req.count, req.repo, req.concurrent)

    async def gen():
        def emit(data):
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        run_started = datetime.now()
        results_detail = []
        error_reasons: list[dict] = []
        uploaded = 0
        errors = 0
        skipped = 0
        upload_phase_start = None
        upload_phase_end = None
        embed_phase_start = None
        embed_phase_end = None
        concurrent_samples: list[int] = []
        cycle_completions: list[dict] = []
        # doc_id → {"name": str, "upload_time": datetime}
        pending_docs: dict[str, dict] = {}

        def _extract_doc_id(res: dict) -> str:
            # 상태 조회 API는 document_id를 사용 (datasource_file_id 아님)
            doc_id = (res.get("document_id")
                      or res.get("id")
                      or res.get("data", {}).get("document_id", "")
                      or res.get("data", {}).get("id", ""))
            ds_id = res.get("datasource_file_id", "")
            logger.info("ingest 응답: document_id=%s, datasource_file_id=%s", doc_id, ds_id)
            return doc_id

        try:
            import random

            # ── 헬퍼: 페이지 단위로 아이템을 가져오는 이터레이터 ──
            async def _fetch_items():
                if req.target == "law":
                    probe = await asyncio.to_thread(search_law, org="1492000", display=1)
                    total_cnt = int(probe.get("total_cnt") or 0)
                    page_size = min(req.count * 2, 100)
                    max_pg = max(1, (total_cnt - 1) // page_size + 1)
                    pg = random.randint(1, max_pg)
                    seen = set()
                    loops = 0
                    while loops < max_pg:
                        actual_pg = ((pg - 1) % max_pg) + 1
                        result = await asyncio.to_thread(search_law, org="1492000", display=page_size, page=actual_pg)
                        for law in result.get("laws", []):
                            lid = law.get("법령명한글", "")
                            if lid and lid not in seen:
                                seen.add(lid)
                                yield law
                        pg += 1
                        loops += 1
                else:
                    prec_laws = [l["name"] for l in _load_batch_prec_config().get("laws", [])] or ["근로기준법"]
                    seen = set()
                    for law_name in prec_laws:
                        if _batch_test_cancel:
                            break
                        try:
                            probe = await asyncio.to_thread(search_prec, jo=law_name, display=1, page=1)
                        except Exception:
                            continue
                        total_cnt = int(probe.get("total_cnt") or 0)
                        if total_cnt == 0:
                            continue
                        max_pg = max(1, (total_cnt - 1) // 100 + 1)
                        pg = random.randint(1, max_pg)
                        loops = 0
                        while loops < max_pg:
                            actual_pg = ((pg - 1) % max_pg) + 1
                            try:
                                batch_res = await asyncio.to_thread(search_prec, jo=law_name, display=100, page=actual_pg)
                            except Exception:
                                break
                            for p in batch_res.get("precs", []):
                                pid = str(p.get("판례정보일련번호") or p.get("판례일련번호") or "")
                                if pid and pid not in seen:
                                    seen.add(pid)
                                    yield p
                            pg += 1
                            loops += 1

            # ── 업로드 헬퍼: 단건 업로드 후 결과 dict 반환 ──
            def _safe_fname(name: str, max_len: int = 80) -> str:
                import re
                return re.sub(r'[\\/:*?"<>|]', '_', name)[:max_len]

            async def upload_one(item) -> dict:
                if req.target == "law":
                    iname = item.get("법령명한글", "")
                    iid   = str(item.get("법령ID", ""))
                    fname_pre = f"{_safe_fname(iname)}.json"
                else:
                    iid   = str(item.get("판례정보일련번호") or item.get("판례일련번호") or "")
                    iname = item.get("사건명", iid)
                    fname_pre = f"{iid}_{_safe_fname(iname)}.json"
                t0 = time.perf_counter()
                # Knowledge에 이미 있으면 API 호출 없이 즉시 스킵
                if fname_pre in existing_names:
                    return {"status": "duplicate", "name": iname, "elapsed": round(time.perf_counter() - t0, 2)}
                try:
                    docs_dir = BATCHTEST_DOCS_DIR / req.target
                    docs_dir.mkdir(parents=True, exist_ok=True)
                    if req.target == "law":
                        detail  = await asyncio.to_thread(get_law, law_id=iid)
                        acnt    = len(detail.get("articles", []))
                        fname   = f"{_safe_fname(iname)}.json"
                        payload = {k: v for k, v in detail.items() if k != "raw"}
                    else:
                        detail  = await asyncio.to_thread(get_prec, prec_id=iid)
                        acnt    = 0
                        fname   = f"{iid}_{_safe_fname(iname)}.json"
                        payload = {k: v for k, v in detail.items() if k != "raw"}
                    content = json.dumps(payload, ensure_ascii=False, indent=2)
                    skb     = round(len(content.encode("utf-8")) / 1024, 1)
                    (docs_dir / fname).write_text(content, encoding="utf-8")
                    meta    = {"category": "배치테스트", "tags": [iname]}
                    if req.target == "prec":
                        meta["prec_id"] = iid
                    res = await asyncio.to_thread(ingest, repo_id, content, fname, meta)
                    return {"status": "ok", "name": iname, "size_kb": skb,
                            "elapsed": round(time.perf_counter() - t0, 2),
                            "doc_id": _extract_doc_id(res), "article_cnt": acnt}
                except KnowledgeDuplicateError:
                    return {"status": "duplicate", "name": iname, "elapsed": round(time.perf_counter() - t0, 2)}
                except Exception as e:
                    msg = str(e)
                    return {"status": "not_found" if ("404" in msg or "Not Found" in msg) else "error",
                            "name": iname, "elapsed": round(time.perf_counter() - t0, 2),
                            "error": f"{type(e).__name__}: {msg[:150]}",
                            "status_code": getattr(e, "status_code", None)}

            def _apply_result(r: dict) -> str:
                nonlocal uploaded, skipped, errors
                name, status, elapsed = r["name"], r["status"], r["elapsed"]
                if status == "ok":
                    uploaded += 1
                    doc_id = r["doc_id"]
                    acnt   = r.get("article_cnt", 0)
                    skb    = r["size_kb"]
                    entry  = {"name": name, "status": "uploaded", "size_kb": skb,
                              "elapsed_sec": elapsed, "doc_id": doc_id, "embed_status": "pending"}
                    if acnt:
                        entry["articles"] = acnt
                    results_detail.append(entry)
                    if doc_id:
                        pending_docs[doc_id] = {"name": name, "upload_time": datetime.now(), "idx": len(results_detail) - 1}
                    else:
                        entry["embed_status"] = "no_doc_id"
                    extra = f", {acnt}조" if acnt else ""
                    return emit({"step": "upload", "status": "done",
                                 "message": f"[{uploaded}/{target_count}] {name} — {skb}KB, {elapsed}초{extra}",
                                 "progress": uploaded, "total": target_count})
                elif status == "duplicate":
                    skipped += 1
                    results_detail.append({"name": name, "status": "duplicate", "elapsed_sec": elapsed, "embed_status": "skip"})
                    return emit({"step": "upload", "status": "done",
                                 "message": f"[{uploaded}/{target_count}] {name} — 중복, 다음으로 대체",
                                 "progress": uploaded, "total": target_count})
                elif status == "not_found":
                    skipped += 1
                    results_detail.append({"name": name, "status": "not_found", "elapsed_sec": elapsed, "embed_status": "skip"})
                    return emit({"step": "upload", "status": "done",
                                 "message": f"[{uploaded}/{target_count}] {name} — 조회 불가(404), 다음으로 대체",
                                 "progress": uploaded, "total": target_count})
                else:
                    errors += 1
                    short_err = r.get("error", "알 수 없는 오류")
                    results_detail.append({"name": name, "status": "error", "error": short_err,
                                           "elapsed_sec": elapsed, "embed_status": "skip"})
                    error_reasons.append({"phase": "upload", "name": name, "error": short_err,
                                          "status_code": r.get("status_code")})
                    return emit({"step": "upload", "status": "error",
                                 "message": f"[{uploaded}/{target_count}] {name} — {short_err}",
                                 "progress": uploaded, "total": target_count})

            # ── 업로드: 성공 건수가 count에 도달할 때까지 (0 = 전체) ──
            target_count  = req.count if req.count > 0 else 10_000_000
            concurrent_n  = max(1, req.concurrent)

            # 기존 Knowledge 문서 파일명 사전 로드 (upload 전 중복 체크로 불필요한 API 호출 방지)
            existing_names: set[str] = set()
            try:
                yield emit({"step": "phase", "status": "info",
                            "message": "── Knowledge 기존 문서 목록 조회 중... ──"})
                existing_names = await asyncio.to_thread(list_document_names, repo_id)
                yield emit({"step": "phase", "status": "info",
                            "message": f"── 기존 문서 {len(existing_names):,}건 확인 ──"})
            except Exception as _e:
                logger.warning("기존 문서 목록 조회 실패 (중복 체크 없이 진행): %s", _e)

            upload_phase_start = datetime.now()
            if req.target == "prec":
                prec_law_cnt = len(_load_batch_prec_config().get("laws", []))
                yield emit({"step": "phase", "status": "info",
                            "message": f"── 판례 수집 법령: 배치 설정 {prec_law_cnt}개 기준 (전체 중복 제거) ──"})
            yield emit({"step": "phase", "status": "start",
                        "message": f"── 업로드 시작: {upload_phase_start.strftime('%H:%M:%S')} "
                                   f"(목표 {target_count}건, 동시 {concurrent_n}건) ──"})

            async def _run_batch(batch: list):
                """배치를 gather로 실행하고 결과 이벤트를 yield"""
                if concurrent_n > 1:
                    yield emit({"step": "upload", "status": "start",
                                "message": f"[{uploaded+1}~{min(uploaded+len(batch), target_count)}/{target_count}] "
                                           f"{len(batch)}건 병렬 업로드 중...",
                                "progress": uploaded, "total": target_count})
                else:
                    first_name = batch[0].get("법령명한글") or batch[0].get("사건명", "")
                    yield emit({"step": "upload", "status": "start",
                                "message": f"[{uploaded+1}/{target_count}] {first_name} 업로드 중...",
                                "progress": uploaded, "total": target_count})
                results = await asyncio.gather(*[upload_one(i) for i in batch])
                for r in results:
                    if uploaded >= target_count:
                        break
                    yield _apply_result(r)

            batch: list = []
            async for item in _fetch_items():
                if _batch_test_cancel:
                    yield emit({"step": "cancel", "status": "error", "message": "사용자 중지"})
                    break
                if uploaded >= target_count:
                    break
                batch.append(item)
                if len(batch) < concurrent_n:
                    continue
                async for ev in _run_batch(batch):
                    yield ev
                batch = []

            if batch and not _batch_test_cancel and uploaded < target_count:
                async for ev in _run_batch(batch):
                    yield ev

            upload_phase_end = datetime.now()
            upload_sec = int((upload_phase_end - upload_phase_start).total_seconds()) if upload_phase_start else 0
            yield emit({"step": "phase", "status": "done",
                        "message": f"── 업로드 완료: {upload_phase_end.strftime('%H:%M:%S')} "
                                   f"(소요 {upload_sec}초, 성공 {uploaded}건, 중복 {skipped}건, 실패 {errors}건) ──"})

            # ── 3단계: 임베딩 상태 확인 ──
            if pending_docs:
                POLL_INTERVAL = 5
                embed_ok = 0
                embed_fail = 0
                embed_timeout = 0

                embed_phase_start = datetime.now()
                total_to_embed = len(pending_docs)
                yield emit({"step": "phase", "status": "start",
                            "message": f"── 임베딩 확인 시작: {embed_phase_start.strftime('%H:%M:%S')} (대기 {total_to_embed}건) ──"})

                poll_start = time.perf_counter()
                concurrent_samples: list[int] = []
                cycle_completions: list[dict] = []
                poll_cycle = 0

                while pending_docs:
                    if _batch_test_cancel:
                        yield emit({"step": "cancel", "status": "error", "message": "사용자 중지"})
                        break

                    poll_cycle += 1
                    done_ids = []
                    indexing_count = 0

                    for doc_id, info in pending_docs.items():
                        try:
                            doc = await asyncio.to_thread(get_document_status, repo_id, doc_id)
                            status = doc.get("status", "unknown")
                            is_indexing = doc.get("is_indexing", True)
                            elapsed_embed = round(time.perf_counter() - poll_start, 1)
                            if poll_cycle == 1:
                                logger.info("문서 상태 응답 (%s): %s", doc_id[:12], {k: v for k, v in doc.items() if k != "raw"})

                            chunk_count = doc.get("chunk_count") or 0
                            chunk_progress = doc.get("embedding_chunk_progress", "")

                            if status == "embedded" and not is_indexing:
                                done_ids.append(doc_id)
                                embed_ok += 1
                                # chunks API로 실제 청크 수 조회
                                try:
                                    ch = await asyncio.to_thread(get_document_chunks, repo_id, doc_id)
                                    chunk_count = ch.get("count", 0) or chunk_count
                                except Exception:
                                    pass
                                results_detail[info["idx"]]["embed_status"] = "embedded"
                                results_detail[info["idx"]]["embed_sec"] = elapsed_embed
                                results_detail[info["idx"]]["chunk_count"] = chunk_count
                                yield emit({"step": "embed", "status": "done",
                                            "message": f"  ✓ {info['name']} — embedded ({elapsed_embed}초, {chunk_count}청크)"})
                            elif status == "failed":
                                done_ids.append(doc_id)
                                embed_fail += 1
                                fail_reason = doc.get("error", "") or doc.get("message", "") or "사유 미제공"
                                results_detail[info["idx"]]["embed_status"] = "failed"
                                results_detail[info["idx"]]["embed_sec"] = elapsed_embed
                                results_detail[info["idx"]]["embed_error"] = str(fail_reason)[:200]
                                error_reasons.append({"phase": "embed", "name": info["name"], "error": str(fail_reason)[:200]})
                                yield emit({"step": "embed", "status": "error",
                                            "message": f"  ✗ {info['name']} — 임베딩 실패 ({elapsed_embed}초): {str(fail_reason)[:100]}"})
                            else:
                                results_detail[info["idx"]]["embed_status"] = status
                                results_detail[info["idx"]]["chunk_count"] = chunk_count
                                results_detail[info["idx"]]["chunk_progress"] = chunk_progress
                                if is_indexing or status in ("indexing", "processing", "parsing", "chunked"):
                                    indexing_count += 1
                                info["check_count"] = info.get("check_count", 0) + 1
                        except Exception as exc:
                            info["fail_count"] = info.get("fail_count", 0) + 1
                            if info["fail_count"] == 1:
                                logger.warning("문서 상태 조회 실패 (%s): %s", doc_id[:12], exc)
                            if info["fail_count"] >= 5:
                                done_ids.append(doc_id)
                                results_detail[info["idx"]]["embed_status"] = "check_failed"
                                yield emit({"step": "embed", "status": "error",
                                            "message": f"  ⚠ {info['name']} — 상태 조회 불가 (doc_id: {doc_id[:20]}...)"})

                    for did in done_ids:
                        del pending_docs[did]

                    # 동시 처리 수 기록
                    active_count = indexing_count or len(pending_docs)
                    concurrent_samples.append(active_count)
                    elapsed_total = round(time.perf_counter() - poll_start, 1)
                    cycle_completions.append({
                        "cycle": poll_cycle, "elapsed": elapsed_total,
                        "completed": len(done_ids), "concurrent": active_count,
                    })

                    if pending_docs:
                        completed_so_far = embed_ok + embed_fail
                        yield emit({"step": "embed", "status": "start",
                                    "message": f"  대기 {len(pending_docs)}건 · 동시처리 {active_count}건 · "
                                               f"완료 {completed_so_far}/{total_to_embed} · {elapsed_total}초 경과"})
                        await asyncio.sleep(POLL_INTERVAL)

                # 남아있는 경우 (check_failed 5회로 빠진 것들)
                for doc_id, info in pending_docs.items():
                    embed_timeout += 1
                    results_detail[info["idx"]]["embed_status"] = "unknown"
                    yield emit({"step": "embed", "status": "error",
                                "message": f"  ⚠ {info['name']} — 상태 미확인"})

                # 동시 처리 통계
                embed_phase_end = datetime.now()
                embed_sec = int((embed_phase_end - embed_phase_start).total_seconds()) if embed_phase_start else 0
                if concurrent_samples:
                    avg_concurrent = round(sum(concurrent_samples) / len(concurrent_samples), 1)
                    max_concurrent = max(concurrent_samples)
                    min_concurrent = min(concurrent_samples)
                else:
                    avg_concurrent = max_concurrent = min_concurrent = 0
                embed_throughput = round(embed_ok / max(embed_sec, 1), 2) if embed_ok else 0

                total_chunks = sum(d.get("chunk_count", 0) for d in results_detail)
                embed_stats_msg = (f"총 {total_chunks}청크 · 동시처리 평균 {avg_concurrent}건 "
                                   f"(최소 {min_concurrent} / 최대 {max_concurrent}), "
                                   f"처리속도 {embed_throughput}건/초")
                yield emit({"step": "embed_stats", "status": "done",
                            "message": f"  📊 {embed_stats_msg}"})
                yield emit({"step": "phase", "status": "done",
                            "message": f"── 임베딩 완료: {embed_phase_end.strftime('%H:%M:%S')} "
                                       f"(소요 {embed_sec}초, 성공 {embed_ok}, 실패 {embed_fail}) ──"})

            # ── 결과 저장 ──
            run_finished = datetime.now()
            total_elapsed = int((run_finished - run_started).total_seconds())
            avg_sec = round(total_elapsed / max(uploaded, 1), 2) if uploaded else 0

            embed_summary = {"embedded": 0, "failed": 0, "timeout": 0, "pending": 0}
            for d in results_detail:
                es = d.get("embed_status", "skip")
                if es in embed_summary:
                    embed_summary[es] += 1

            # 동시처리 통계 (임베딩 단계가 없으면 기본값)
            total_chunks = sum(d.get("chunk_count", 0) for d in results_detail)
            if not concurrent_samples:
                avg_concurrent = max_concurrent = min_concurrent = 0
                embed_throughput = 0
                cycle_completions = []

            upload_sec = int((upload_phase_end - upload_phase_start).total_seconds()) if upload_phase_start and upload_phase_end else 0
            embed_sec = int((embed_phase_end - embed_phase_start).total_seconds()) if embed_phase_start and embed_phase_end else 0

            summary = {
                "id": str(uuid.uuid4())[:8],
                "run_at": run_started.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": run_finished.strftime("%Y-%m-%d %H:%M:%S"),
                "target": req.target,
                "repo": req.repo,
                "concurrent": concurrent_n,
                "requested": req.count,
                "uploaded": uploaded,
                "skipped": skipped,
                "errors": errors,
                "embed": embed_summary,
                "total_chunks": total_chunks,
                "embed_concurrency": {
                    "avg": avg_concurrent,
                    "min": min_concurrent,
                    "max": max_concurrent,
                    "throughput": embed_throughput,
                    "samples": concurrent_samples,
                    "cycles": cycle_completions,
                },
                "total_sec": total_elapsed,
                "upload_sec": upload_sec,
                "embed_sec": embed_sec,
                "avg_sec": avg_sec,
                "error_reasons": error_reasons,
                "details": results_detail,
            }
            existing = _load_batch_test_results()
            existing.insert(0, summary)
            _save_batch_test_results(existing[:30])

            yield emit({"step": "done", "status": "done",
                        "message": f"완료 — 업로드 {uploaded}건({upload_sec}초), 임베딩 {embed_summary['embedded']}건({embed_sec}초), "
                                   f"중복 {skipped}건, 실패 {errors}건, "
                                   f"총 {total_elapsed}초 ({run_started.strftime('%H:%M:%S')}~{run_finished.strftime('%H:%M:%S')})",
                        "summary": summary})

        except Exception as e:
            yield emit({"step": "error", "status": "error",
                        "message": f"테스트 실패: {type(e).__name__}: {str(e)[:200]}"})
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


# ── 서버 시작 ───────────────────────────────────────────────────

def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((CHAT_HOST, CHAT_PORT))
        sock.close()
    except OSError:
        print(f"포트 {CHAT_PORT}이(가) 이미 사용 중입니다.")
        print(f"  다른 포트: CHAT_PORT=8081 python run.py")
        print(f"  기존 프로세스 종료: netstat -ano | findstr :{CHAT_PORT}")
        sys.exit(1)

    print(f"채팅 서버: http://{CHAT_HOST}:{CHAT_PORT}")
    import uvicorn
    uvicorn.run("web.app:app", host=CHAT_HOST, port=CHAT_PORT, reload=True)


if __name__ == "__main__":
    start_server()
