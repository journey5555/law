"""에이전트 채팅 웹 서버"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
import logging
import logging.handlers
import socket
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
from clients.knowledge_client import KnowledgeApiError, KnowledgeDuplicateError, delete_documents, hard_delete_datasource, ingest, get_document_status, law_to_markdown, prec_to_markdown
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
    from pharma.routes import router as pharma_router, sync_emails_job, check_overdue_job

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
LAW_STATES_FILE        = _DATA_DIR / "law_states.json"
PREC_STATES_FILE       = _DATA_DIR / "prec_states.json"
BATCH_LAW_LOGS_FILE    = _DATA_DIR / "batch_logs.json"
BATCH_PREC_LOGS_FILE   = _DATA_DIR / "batch_prec_logs.json"
NOTIFICATIONS_FILE     = _DATA_DIR / "notifications.json"


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


async def _run_law_batch() -> dict:
    """법령 본문 일괄 수집 배치"""
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

    for law_entry in laws_to_check:
        law_name = law_entry["name"] if isinstance(law_entry, dict) else str(law_entry)
        state    = states.get(law_name, {})
        if not state.get("active", True):
            results.append({"name": law_name, "status": "비활성", "message": "폐지 비활성"})
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
            PREC_DISPLAY = 100
            prec_page    = 1
            new_prec_cnt = 0
            all_precs: list = []

            while True:
                pr = search_prec(jo=law_name, display=PREC_DISPLAY, page=prec_page)
                if prec_page == 1:
                    new_prec_cnt = int(pr.get("total_cnt") or 0)
                batch_precs = pr.get("precs", [])
                all_precs.extend(batch_precs)
                if len(all_precs) >= new_prec_cnt or len(batch_precs) < PREC_DISPLAY:
                    break
                prec_page += 1

            old_prec_cnt = state.get("last_prec_count")
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
    _register_law_batch_job(_load_batch_law_config().get("run_time", "02:00"))
    _register_prec_batch_job(_load_batch_prec_config().get("run_time", "03:00"))
    if PHARMA_ENABLED:
        pharma_init_db()
        _scheduler.add_job(sync_emails_job,   "interval", minutes=PHARMA_CHECK_INTERVAL_MIN,
                           id="pharma_email_sync",    coalesce=True, misfire_grace_time=300)
        _scheduler.add_job(check_overdue_job, "interval", hours=1,
                           id="pharma_overdue_check", coalesce=True, misfire_grace_time=300)
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
