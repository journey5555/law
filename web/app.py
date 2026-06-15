"""에이전트 채팅 웹 서버"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
import logging
import logging.handlers
import socket
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from clients.agent_client import AgentApiError, invoke_agent, stream_agent_tokens
from clients.knowledge_client import KnowledgeApiError, KnowledgeDuplicateError, delete_documents, ingest, law_to_markdown, prec_to_markdown
from clients.law_client import LawApiError, format_jo, get_law, get_prec, search_law, search_prec
from config import (
    AGENT_API_KEY, AGENT_ID, CHAT_HOST, CHAT_PORT, LOG_LEVEL,
    KNOWLEDGE_LAW_REPO_ID, KNOWLEDGE_PREC_REPO_ID,
    SUMMARIZE_AGENT_ID, SUMMARIZE_API_KEY,
    LAW_PREC_AGENT_ID, LAW_PREC_AGENT_API_KEY,
    PHARMA_CHECK_INTERVAL_MIN,
)

from config import PHARMA_ENABLED
if PHARMA_ENABLED:
    from pharma.db import init_db as pharma_init_db
    from pharma.routes import router as pharma_router, sync_emails_job, check_overdue_job

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
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

_scheduler   = AsyncIOScheduler(timezone="Asia/Seoul")
_schedule_lock = asyncio.Lock()

_WEEKDAY_MAP = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri", "토": "sat", "일": "sun"}


def _fmt_interval(interval: str, day: Optional[str], time: Optional[str]) -> str:
    t = f" {time}" if time else ""
    if interval == "daily":   return f"매일{t}"
    if interval == "weekly":  return (f"매주 {day}요일{t}" if day else f"매주{t}")
    if interval == "monthly": return (f"매월 {day}일{t}"  if day else f"매월{t}")
    return interval


def _make_trigger(interval: str, day: Optional[str], time: Optional[str]) -> CronTrigger:
    try:
        h, m = map(int, (time or "09:00").split(":"))
    except Exception:
        h, m = 9, 0
    if interval == "weekly":
        return CronTrigger(day_of_week=_WEEKDAY_MAP.get(day or "월", "mon"), hour=h, minute=m, timezone="Asia/Seoul")
    if interval == "monthly":
        return CronTrigger(day=int(day or "1"), hour=h, minute=m, timezone="Asia/Seoul")
    return CronTrigger(hour=h, minute=m, timezone="Asia/Seoul")


def _register_job(law: dict) -> None:
    law_id = law["id"]
    trigger = _make_trigger(law.get("interval", "daily"), law.get("day"), law.get("time"))
    job_id  = f"law_{law_id}"
    if _scheduler.get_job(job_id):
        _scheduler.reschedule_job(job_id, trigger=trigger)
    else:
        _scheduler.add_job(_auto_run_law, trigger, id=job_id, args=[law_id],
                           misfire_grace_time=3600, coalesce=True)
    logger.info("스케줄 등록: %s (%s)", law.get("name"), law.get("interval"))


def _remove_job(law_id: str) -> None:
    job_id = f"law_{law_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


async def _auto_run_law(law_id: str) -> None:
    async with _schedule_lock:
        logger.info("자동 수집 시작: %s", law_id)
        try:
            await _do_run_law(law_id)
        except Exception as e:
            logger.error("자동 수집 실패 (%s): %s", law_id, e)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    data = _load_schedules()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for law in data.get("laws", []):
        # next_run을 미래로 재계산해서 시작 즉시 실행 방지
        next_run = law.get("next_run")
        if not next_run or next_run <= now_str:
            law["next_run"] = _calc_next_run(law.get("interval", "daily"), law.get("day"), law.get("time"))
        _register_job(law)
    _save_schedules(data)
    # Pharma Monitor 초기화
    if PHARMA_ENABLED:
        pharma_init_db()
        _scheduler.add_job(sync_emails_job,  "interval", minutes=PHARMA_CHECK_INTERVAL_MIN, id="pharma_email_sync",    coalesce=True, misfire_grace_time=300)
        _scheduler.add_job(check_overdue_job,"interval", hours=1,                           id="pharma_overdue_check", coalesce=True, misfire_grace_time=300)
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


SCHEDULES_FILE      = Path(__file__).resolve().parent.parent / "data" / "schedules.json"
PRESETS_FILE        = Path(__file__).resolve().parent.parent / "data" / "law_presets.json"
NOTIFICATIONS_FILE  = Path(__file__).resolve().parent.parent / "data" / "notifications.json"

INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}

def _load_schedules() -> dict:
    if not SCHEDULES_FILE.exists():
        return {"laws": [], "logs": []}
    return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))

def _save_schedules(data: dict) -> None:
    SCHEDULES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_notifications() -> dict:
    if not NOTIFICATIONS_FILE.exists():
        return {"notifications": []}
    return json.loads(NOTIFICATIONS_FILE.read_text(encoding="utf-8"))

def _save_notifications(data: dict) -> None:
    NOTIFICATIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

def _calc_next_run(interval: str, day: Optional[str] = None, time: Optional[str] = None) -> str:
    now = datetime.now()
    try:
        h, m = map(int, (time or "09:00").split(":"))
        h, m = max(0, min(23, h)), max(0, min(59, m))
    except Exception:
        h, m = 9, 0

    if interval == "weekly":
        day_map = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
        target = day_map.get(day or "월", 0)
        days_ahead = (target - now.weekday()) % 7
        next_dt = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(weeks=1)
    elif interval == "monthly":
        try:
            target_day = max(1, min(28, int(day or "1")))
        except (ValueError, TypeError):
            target_day = 1
        if now.day < target_day:
            next_dt = now.replace(day=target_day, hour=h, minute=m, second=0, microsecond=0)
        else:
            next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
            next_dt = next_month.replace(day=target_day, hour=h, minute=m, second=0, microsecond=0)
        if next_dt <= now:
            next_month = (next_dt.replace(day=1) + timedelta(days=32)).replace(day=1)
            next_dt = next_month.replace(day=target_day, hour=h, minute=m, second=0, microsecond=0)
    else:
        next_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)
    return next_dt.strftime("%Y-%m-%d %H:%M:%S")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)


class LawSchedule(BaseModel):
    name: str = Field(..., min_length=1)
    interval: str = Field(..., pattern="^(daily|weekly|monthly)$")
    day: Optional[str] = None
    time: Optional[str] = None
    collect_type: str = Field("전체", pattern="^(전체|법령|판례)$")


class LawScheduleUpdate(BaseModel):
    name: Optional[str] = None
    interval: Optional[str] = Field(None, pattern="^(daily|weekly|monthly)$")
    day: Optional[str] = None
    time: Optional[str] = None
    collect_type: Optional[str] = Field(None, pattern="^(전체|법령|판례)$")


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
    }


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
        return {
            "content": result["content"],
            "run_id": result.get("run_id"),
        }
    except AgentApiError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e),
        ) from e


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    message = req.message.strip()
    logger.info("채팅 요청 (stream): %s", message[:100])

    def event_generator():
        try:
            for token in stream_agent_tokens(message):
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except AgentApiError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/lawprec/chat/stream")
async def lawprec_chat_stream(req: ChatRequest):
    message = req.message.strip()
    logger.info("법률판례질의 요청 (stream): %s", message[:100])

    if not LAW_PREC_AGENT_ID or not LAW_PREC_AGENT_API_KEY:
        raise HTTPException(status_code=503, detail="LAW_PREC_AGENT_ID / LAW_PREC_AGENT_API_KEY가 설정되지 않았습니다.")

    def event_generator():
        try:
            for token in stream_agent_tokens(message, agent_id=LAW_PREC_AGENT_ID, api_key=LAW_PREC_AGENT_API_KEY):
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except AgentApiError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


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
        laws = result["laws"]
        if not laws:
            raise HTTPException(status_code=404, detail=f"'{law_name}' 법령을 찾을 수 없습니다.")

        # 1순위: 정확히 일치, 2순위: law_name으로 시작, 3순위: 첫 번째 결과
        target = (
            next((l for l in laws if l.get("법령명한글") == law_name), None)
            or next((l for l in laws if l.get("법령명한글", "").startswith(law_name)), None)
            or laws[0]
        )

        law_id = str(target["법령ID"])
        law_full_name = target.get("법령명한글", law_name)
        logger.info("  매칭된 법령: %s (ID=%s)", law_full_name, law_id)

        detail = get_law(law_id=law_id, jo=format_jo(jo, jo_sub))
        detail["searched_law_name"] = law_full_name
        detail["searched_jo"] = jo

        if not detail.get("articles"):
            raise HTTPException(
                status_code=404,
                detail=f"'{law_full_name}' 제{jo}조를 찾을 수 없습니다."
            )

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
async def prec_search(q: str = "", page: int = 1, display: int = 15):
    logger.info("판례 검색: %s", q or "(전체)")
    try:
        return search_prec(query=q or None, page=page, display=display)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/prec/{prec_id}")
async def prec_detail(prec_id: str):
    logger.info("판례 조회: %s", prec_id)
    try:
        return get_prec(prec_id=prec_id)
    except LawApiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/scheduler/presets")
async def scheduler_presets():
    if not PRESETS_FILE.exists():
        return {"presets": []}
    return {"presets": json.loads(PRESETS_FILE.read_text(encoding="utf-8"))}


@app.get("/api/scheduler/laws")
async def scheduler_laws():
    data = _load_schedules()
    return {"laws": data.get("laws", [])}


@app.post("/api/scheduler/laws", status_code=201)
async def scheduler_add_law(body: LawSchedule):
    data  = _load_schedules()
    ndata = _load_notifications()
    new_law = {
        "id": str(uuid.uuid4())[:8],
        "name": body.name,
        "interval": body.interval,
        "day": body.day,
        "time": body.time or "09:00",
        "collect_type": body.collect_type,
        "status": "idle",
        "last_run": None,
        "next_run": None,
        "last_enforcement_date": None,
        "last_prec_count": None,
    }
    data["laws"].append(new_law)
    try:
        sr = search_law(query=body.name, display=3)
        ml = next((l for l in sr["laws"] if l.get("법령명한글") == body.name), sr["laws"][0] if sr["laws"] else None)
        new_preview: Optional[dict] = {"rows": [
            {"label": "소관부처", "value": ml.get("소관부처명", "-")},
            {"label": "법령구분", "value": ml.get("법령구분명", "-")},
            {"label": "시행일자", "value": _fmt_date(str(ml.get("시행일자", "")))},
        ]} if ml else None
    except Exception:
        new_preview = None
    _push_notification(ndata, "신규", body.name,
        f"수집 대상 추가: {body.name}",
        f"수집 주기: {_fmt_interval(body.interval, body.day, body.time)} · 수집 대상: {body.collect_type}",
        preview=new_preview)
    _save_schedules(data)
    _save_notifications(ndata)
    _register_job(new_law)
    logger.info("수집 대상 추가: %s (%s)", body.name, body.interval)
    return new_law


@app.put("/api/scheduler/laws/{law_id}")
async def scheduler_update_law(law_id: str, body: LawScheduleUpdate):
    data = _load_schedules()
    law = next((l for l in data["laws"] if l["id"] == law_id), None)
    if not law:
        raise HTTPException(status_code=404, detail="법령을 찾을 수 없습니다.")
    if body.name is not None:
        law["name"] = body.name
    if body.interval is not None:
        law["interval"] = body.interval
        law["day"] = body.day
    elif body.day is not None:
        law["day"] = body.day
    if body.time is not None:
        law["time"] = body.time
    if body.collect_type is not None:
        law["collect_type"] = body.collect_type
    _save_schedules(data)
    _register_job(law)
    return law


@app.delete("/api/scheduler/laws/{law_id}", status_code=204)
async def scheduler_delete_law(law_id: str):
    data  = _load_schedules()
    ndata = _load_notifications()
    law   = next((l for l in data["laws"] if l["id"] == law_id), None)
    if not law:
        raise HTTPException(status_code=404, detail="법령을 찾을 수 없습니다.")
    data["laws"] = [l for l in data["laws"] if l["id"] != law_id]
    _push_notification(ndata, "삭제", law["name"],
        f"수집 대상 삭제: {law['name']}",
        f"수집 주기: {_fmt_interval(law.get('interval','daily'), law.get('day'), law.get('time'))} · 수집 대상: {law.get('collect_type', '전체')}")
    _save_schedules(data)
    _save_notifications(ndata)
    _remove_job(law_id)


async def _do_run_law(law_id: str) -> dict:
    data  = _load_schedules()
    ndata = _load_notifications()
    law = next((l for l in data["laws"] if l["id"] == law_id), None)
    if not law:
        raise ValueError(f"법령 없음: {law_id}")

    started = datetime.now()
    law["status"] = "running"
    _save_schedules(data)

    law_name     = law["name"]
    collect_type = law.get("collect_type", "전체")
    status = "success"
    count  = 0
    msgs: list[str] = []

    try:
        # ── 법령 검색 & 개정 감지 ──────────────────────────────────────
        if collect_type in ("전체", "법령"):
            result = search_law(query=law_name, display=10)
            count += result.get("total_cnt", 0)
            laws   = result.get("laws", [])
        else:
            laws = []

        # 개정 감지는 정확히 일치하는 법령명 기준
        matched = next(
            (l for l in laws if l.get("법령명한글") == law_name),
            laws[0] if laws else None,
        )
        if matched:
            new_ef = str(matched.get("시행일자") or "")
            old_ef = str(law.get("last_enforcement_date") or "")
            law_changed = old_ef and new_ef and new_ef != old_ef
            if law_changed:
                amend_preview: Optional[dict] = {"rows": [
                    {"label": "소관부처", "value": matched.get("소관부처명", "-")},
                    {"label": "법령구분", "value": matched.get("법령구분명", "-")},
                    {"label": "공포일자", "value": _fmt_date(str(matched.get("공포일자", "")))},
                    {"label": "신규 시행일", "value": _fmt_date(new_ef)},
                ]} if matched else None
                _push_notification(ndata, "개정", law_name,
                    f"법령 개정: {law_name}",
                    f"시행일자 변경  {_fmt_date(old_ef)} → {_fmt_date(new_ef)}",
                    preview=amend_preview)
                msgs.append(f"개정감지({_fmt_date(old_ef)}→{_fmt_date(new_ef)})")
            law["last_enforcement_date"] = new_ef or old_ef

        # ── 법령 Knowledge 업로드 (현재 시행 중인 것만, 개정 또는 미등록) ──
        today_str = datetime.now().strftime("%Y%m%d")
        laws_in_force = [
            l for l in laws
            if str(l.get("시행일자") or "").replace("-", "") <= today_str
        ]
        never_uploaded = not law.get("last_knowledge_upload")
        if KNOWLEDGE_LAW_REPO_ID and laws_in_force and (law_changed or never_uploaded):
            # 개정된 경우 기존 Knowledge 문서 먼저 삭제
            existing_doc_ids: dict = law.get("knowledge_doc_ids") or {}
            if law_changed and existing_doc_ids:
                try:
                    delete_documents(KNOWLEDGE_LAW_REPO_ID, list(existing_doc_ids.values()))
                    law["knowledge_doc_ids"] = {}
                    logger.info("기존 법령 Knowledge 문서 삭제: %d건", len(existing_doc_ids))
                except KnowledgeApiError as ke:
                    logger.warning("법령 Knowledge 문서 삭제 실패: %s", ke)

            new_doc_ids: dict = {}
            law_uploaded = 0
            law_failed: list[tuple[str, str]] = []
            for l in laws_in_force:
                l_id   = str(l.get("법령ID") or "")
                l_name = l.get("법령명한글") or l.get("법령명") or l_id
                if not l_id:
                    continue
                try:
                    law_detail = get_law(law_id=l_id)
                    all_articles = law_detail.get("articles", [])
                    CHUNK = 50
                    chunks = [all_articles[i:i+CHUNK] for i in range(0, max(len(all_articles), 1), CHUNK)] if all_articles else [[]]
                    chunk_uploaded = 0
                    for chunk in chunks:
                        if not chunk:
                            continue
                        start = chunk[0].get("조문번호", "")
                        end   = chunk[-1].get("조문번호", "")
                        suffix = f"_{start}-{end}조" if len(chunks) > 1 else ""
                        fname  = f"{l_name}{suffix}.md"
                        md = law_to_markdown(law_detail, articles=chunk)
                        try:
                            result = ingest(
                                KNOWLEDGE_LAW_REPO_ID,
                                md,
                                fname,
                                metadata={"category": "법령", "tags": [law_name, l_name]},
                            )
                            doc_id = (result or {}).get("datasource_file_id")
                            if doc_id:
                                new_doc_ids[fname] = doc_id
                            chunk_uploaded += 1
                            logger.info("법령 Knowledge 업로드: %s (doc_id=%s)", fname, doc_id)
                        except KnowledgeDuplicateError:
                            chunk_uploaded += 1
                            logger.info("법령 Knowledge 이미 존재 (skip): %s", fname)
                    if chunk_uploaded:
                        law_uploaded += 1
                    else:
                        law_failed.append((l_name, "업로드된 청크 없음"))
                except KnowledgeApiError as ke:
                    law_failed.append((l_name, str(ke)))
                    logger.warning("법령 Knowledge 업로드 실패 (%s): %s", l_name, ke)
            if law_uploaded:
                law["knowledge_doc_ids"] = new_doc_ids
                law["last_knowledge_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msgs.append(f"법령 Knowledge {law_uploaded}건 업로드")
            if law_failed:
                fail_names = ", ".join(name for name, _ in law_failed)
                msgs.append(f"법령 업로드 실패: {fail_names}")
                body_lines = "; ".join(
                    f"{name}: {reason[:60]}" if reason else name
                    for name, reason in law_failed[:3]
                )
                if len(law_failed) > 3:
                    body_lines += f" 외 {len(law_failed)-3}건"
                _push_notification(ndata, "실패", law_name,
                    f"법령 Knowledge 업로드 실패: {law_name}",
                    body_lines)

        # ── 판례 검색 & 신규 판례 감지 ────────────────────────────────
        if collect_type in ("전체", "판례"):
            prec_result  = search_prec(query=law_name, display=5)
            new_prec_cnt = int(prec_result.get("total_cnt") or 0)
            count       += new_prec_cnt
            top_precs    = prec_result.get("precs", [])
        else:
            new_prec_cnt = law.get("last_prec_count") or 0
            top_precs    = []
        old_prec_cnt = law.get("last_prec_count")

        prec_changed = old_prec_cnt is not None and new_prec_cnt > int(old_prec_cnt)
        if prec_changed:
            diff = new_prec_cnt - int(old_prec_cnt)
            prec_preview: Optional[dict] = {"items": [
                {
                    "name":  p.get("사건명", "-"),
                    "no":    p.get("사건번호", "-"),
                    "court": p.get("법원명", "-"),
                    "date":  _fmt_date(str(p.get("선고일자", ""))),
                }
                for p in top_precs[:3]
            ]} if top_precs else None
            _push_notification(ndata, "판례", law_name,
                f"판례 신규 추가: {law_name}",
                f"{diff}건 신규 추가 (누적 {new_prec_cnt:,}건)",
                preview=prec_preview)
            msgs.append(f"판례+{diff}건")

        # ── 판례 Knowledge 업로드 (미업로드 건만) ────────────────────
        if KNOWLEDGE_PREC_REPO_ID and top_precs:
            uploaded_ids: set = set(law.get("uploaded_prec_ids") or [])
            prec_uploaded = 0
            prec_failed: list[tuple[str, str]] = []
            for p in top_precs:
                prec_id = str(p.get("판례정보일련번호") or p.get("판례일련번호") or "")
                if not prec_id or prec_id in uploaded_ids:
                    continue
                try:
                    prec_detail = get_prec(prec_id=prec_id)
                    md = prec_to_markdown(prec_detail)
                    case_name = prec_detail.get("case_name") or p.get("사건명", prec_id)
                    ingest(
                        KNOWLEDGE_PREC_REPO_ID,
                        md,
                        f"{case_name}.md",
                        metadata={"category": "판례", "tags": [law_name, case_name]},
                    )
                    uploaded_ids.add(prec_id)
                    prec_uploaded += 1
                    logger.info("판례 Knowledge 업로드: %s", case_name)
                except KnowledgeDuplicateError:
                    # 동일 파일명이 이미 존재 → 업로드된 것으로 간주
                    uploaded_ids.add(prec_id)
                    prec_uploaded += 1
                    logger.info("판례 Knowledge 이미 존재 (skip): %s", prec_id)
                except KnowledgeApiError as ke:
                    prec_failed.append((p.get("사건명", prec_id), str(ke)))
                    logger.warning("판례 Knowledge 업로드 실패 (%s): %s", prec_id, ke)
            if prec_uploaded:
                law["uploaded_prec_ids"] = list(uploaded_ids)
                law["last_prec_knowledge_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msgs.append(f"판례 Knowledge {prec_uploaded}건 업로드")
            if prec_failed:
                msgs.append(f"판례 업로드 실패 {len(prec_failed)}건")
                body_lines = "; ".join(
                    f"{name}: {reason[:60]}" if reason else name
                    for name, reason in prec_failed[:3]
                )
                if len(prec_failed) > 3:
                    body_lines += f" 외 {len(prec_failed)-3}건"
                _push_notification(ndata, "실패", law_name,
                    f"판례 Knowledge 업로드 실패: {law_name}",
                    body_lines)

        law["last_prec_count"] = new_prec_cnt

        # 변동 없거나 첫 수집이라 msgs가 비어있는 경우 기본 요약 추가
        if not msgs:
            if collect_type == "판례":
                msgs.append(f"판례 {new_prec_cnt}건 확인")
            elif collect_type == "법령":
                msgs.append(f"법령 {len(laws)}건 확인")
            else:
                msgs.append(f"법령 {len(laws)}건, 판례 {new_prec_cnt}건 확인")

        msgs_str = ", ".join(msgs)

    except LawApiError as e:
        status   = "failed"
        msgs_str = str(e)
        _push_notification(ndata, "실패", law_name,
            f"수집 실패: {law_name}",
            str(e))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    law["status"]   = status
    law["last_run"] = now_str
    law["next_run"] = _calc_next_run(law["interval"], law.get("day"), law.get("time"))

    log_entry = {
        "id": str(uuid.uuid4())[:8],
        "law_id": law_id,
        "law_name": law_name,
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": now_str,
        "status": status,
        "count": count,
        "message": msgs_str,
    }
    data["logs"].insert(0, log_entry)
    data["logs"] = data["logs"][:100]
    _save_schedules(data)
    _save_notifications(ndata)
    logger.info("수집 실행: %s → %s (%s)", law_name, status, msgs_str)
    return log_entry


@app.post("/api/scheduler/laws/{law_id}/run")
async def scheduler_run_law(law_id: str):
    data = _load_schedules()
    if not any(l["id"] == law_id for l in data.get("laws", [])):
        raise HTTPException(status_code=404, detail="법령을 찾을 수 없습니다.")
    async with _schedule_lock:
        try:
            return await _do_run_law(law_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e


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


@app.get("/api/scheduler/logs")
async def scheduler_logs(law_id: Optional[str] = None):
    data = _load_schedules()
    logs = data.get("logs", [])
    if law_id:
        logs = [l for l in logs if l.get("law_id") == law_id]
    return {"logs": logs}


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
