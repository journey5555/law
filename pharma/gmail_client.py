import base64
import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests as _requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import PHARMA_GMAIL_REDIRECT_URI, PHARMA_GMAIL_SCOPES, PUBSUB_PROJECT_ID, PUBSUB_TOPIC_NAME, PUBSUB_SUBSCRIPTION_NAME

logger = logging.getLogger("pharma.gmail")

_BASE_DIR        = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = _BASE_DIR / "credentials" / "pharma_client_secret.json"
TOKEN_FILE       = _BASE_DIR / "credentials" / "pharma_token.json"
_VERIFIER_FILE   = _BASE_DIR / "credentials" / "pharma_pkce.json"

_TOKEN_URL   = "https://oauth2.googleapis.com/token"
_PUBSUB_BASE = "https://pubsub.googleapis.com/v1"
WATCH_FILE   = _BASE_DIR / "credentials" / "pharma_watch.json"


def _load_client_info() -> dict:
    raw = json.loads(CREDENTIALS_FILE.read_text())
    return raw.get("web") or raw.get("installed") or {}


def get_auth_url() -> str:
    verifier  = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    _VERIFIER_FILE.write_text(json.dumps({"verifier": verifier}))

    info = _load_client_info()
    params = {
        "client_id":             info["client_id"],
        "redirect_uri":          PHARMA_GMAIL_REDIRECT_URI,
        "response_type":         "code",
        "scope":                 " ".join(PHARMA_GMAIL_SCOPES),
        "access_type":           "offline",
        "prompt":                "consent",
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_code(code: str) -> None:
    verifier = None
    if _VERIFIER_FILE.exists():
        try:
            verifier = json.loads(_VERIFIER_FILE.read_text()).get("verifier")
        finally:
            _VERIFIER_FILE.unlink(missing_ok=True)

    info = _load_client_info()
    data = {
        "code":          code,
        "client_id":     info["client_id"],
        "client_secret": info["client_secret"],
        "redirect_uri":  PHARMA_GMAIL_REDIRECT_URI,
        "grant_type":    "authorization_code",
        "code_verifier": verifier,
    }
    resp = _requests.post(_TOKEN_URL, data=data, timeout=30)
    logger.info("토큰 교환 응답 (%d): %s", resp.status_code, resp.text[:500])
    if not resp.ok:
        raise RuntimeError(f"토큰 교환 실패 ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))).isoformat()
    token_data = {
        "token":         data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "token_uri":     _TOKEN_URL,
        "client_id":     info["client_id"],
        "client_secret": info["client_secret"],
        "scopes":        PHARMA_GMAIL_SCOPES,
        "expiry":        expiry,
    }
    TOKEN_FILE.write_text(json.dumps(token_data))
    logger.info("Gmail 인증 완료")


def get_credentials() -> Credentials | None:
    if not TOKEN_FILE.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), PHARMA_GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        except Exception as e:
            logger.error("토큰 갱신 실패: %s", e)
            return None
    return creds if creds.valid else None


def is_connected() -> bool:
    return get_credentials() is not None


def search_emails(query: str, max_results: int = 20) -> list[dict]:
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Gmail 미연결")
    service = build("gmail", "v1", credentials=creds)
    try:
        res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return [_parse_message(service.users().messages().get(userId="me", id=m["id"], format="full").execute())
                for m in res.get("messages", [])]
    except HttpError as e:
        logger.error("Gmail API 오류: %s", e)
        raise


def _parse_message(msg: dict) -> dict:
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    return {
        "id":          msg["id"],
        "sender":      headers.get("from", ""),
        "subject":     headers.get("subject", ""),
        "date":        headers.get("date", ""),
        "body":        _extract_body(payload),
        "attachments": _extract_attachments(payload),
    }


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def _extract_attachments(payload: dict) -> list[dict]:
    results = []
    for part in payload.get("parts", []):
        fname  = part.get("filename", "")
        mime   = part.get("mimeType", "")
        body   = part.get("body", {})
        size   = body.get("size", 0)
        att_id = body.get("attachmentId", "")
        if fname and att_id:
            results.append({"filename": fname, "mime_type": mime, "size": size, "attachment_id": att_id})
        results.extend(_extract_attachments(part))
    return results


def _pubsub_headers() -> dict:
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Gmail 미연결")
    creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}


def start_watch() -> dict:
    """Gmail → Pub/Sub watch 시작 (7일마다 갱신 필요)"""
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Gmail 미연결")
    service = build("gmail", "v1", credentials=creds)
    topic = f"projects/{PUBSUB_PROJECT_ID}/topics/{PUBSUB_TOPIC_NAME}"
    result = service.users().watch(userId="me", body={
        "topicName": topic,
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "INCLUDE",
    }).execute()
    watch_data = {
        "history_id":  str(result["historyId"]),
        "expiration":  result["expiration"],
        "started_at":  datetime.now(timezone.utc).isoformat(),
        "topic":       topic,
        "subscription": f"projects/{PUBSUB_PROJECT_ID}/subscriptions/{PUBSUB_SUBSCRIPTION_NAME}",
    }
    WATCH_FILE.write_text(json.dumps(watch_data, indent=2))
    logger.info("Gmail watch 시작: historyId=%s, 만료=%s", result["historyId"], result["expiration"])
    return watch_data


def stop_watch() -> None:
    creds = get_credentials()
    if not creds:
        return
    build("gmail", "v1", credentials=creds).users().stop(userId="me").execute()
    if WATCH_FILE.exists():
        WATCH_FILE.unlink()
    logger.info("Gmail watch 중지")


def get_watch_status() -> dict:
    if not WATCH_FILE.exists():
        return {"active": False}
    data = json.loads(WATCH_FILE.read_text())
    expiry_ms = int(data.get("expiration", 0))
    expiry_dt = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)
    remaining  = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
    return {
        "active":      remaining > 0,
        "history_id":  data.get("history_id"),
        "expiration":  expiry_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "remaining_h": round(remaining / 3600, 1),
        "subscription": data.get("subscription"),
    }


def pull_and_process() -> list[dict]:
    """Pub/Sub pull → 새 Gmail 메시지 목록 반환"""
    if not WATCH_FILE.exists() or not PUBSUB_PROJECT_ID:
        return []

    watch_data = json.loads(WATCH_FILE.read_text())
    sub_path   = watch_data.get("subscription", f"projects/{PUBSUB_PROJECT_ID}/subscriptions/{PUBSUB_SUBSCRIPTION_NAME}")

    try:
        headers = _pubsub_headers()
    except Exception:
        return []

    # Pull
    resp = _requests.post(
        f"{_PUBSUB_BASE}/{sub_path}:pull",
        json={"maxMessages": 20},
        headers=headers,
        timeout=30,
    )
    if not resp.ok:
        logger.warning("Pub/Sub pull 실패 (%d): %s", resp.status_code, resp.text[:200])
        return []

    received = resp.json().get("receivedMessages", [])
    if not received:
        return []

    # Acknowledge
    ack_ids = [m["ackId"] for m in received]
    _requests.post(
        f"{_PUBSUB_BASE}/{sub_path}:acknowledge",
        json={"ackIds": ack_ids},
        headers=headers,
        timeout=30,
    )

    # 가장 최신 historyId 추출
    last_history_id = watch_data.get("history_id", "0")
    new_history_id  = last_history_id
    for msg in received:
        try:
            payload = json.loads(base64.urlsafe_b64decode(msg["message"]["data"]))
            hid = str(payload.get("historyId", "0"))
            if int(hid) > int(new_history_id):
                new_history_id = hid
        except Exception:
            pass

    # history.list로 실제 추가된 메시지 조회
    new_messages: list[dict] = []
    try:
        creds   = get_credentials()
        service = build("gmail", "v1", credentials=creds)
        history_resp = service.users().history().list(
            userId="me",
            startHistoryId=last_history_id,
            historyTypes=["messageAdded"],
            labelId="INBOX",
        ).execute()
        for h in history_resp.get("history", []):
            for added in h.get("messagesAdded", []):
                mid = added["message"]["id"]
                try:
                    full = service.users().messages().get(userId="me", id=mid, format="full").execute()
                    new_messages.append(_parse_message(full))
                except Exception as e:
                    logger.warning("메시지 조회 실패 (%s): %s", mid, e)
    except Exception as e:
        logger.error("history.list 실패: %s", e)

    # historyId 갱신
    if new_history_id != last_history_id:
        watch_data["history_id"] = new_history_id
        WATCH_FILE.write_text(json.dumps(watch_data, indent=2))

    if new_messages:
        logger.info("Pub/Sub: 새 메시지 %d건", len(new_messages))
    return new_messages


def send_email(to: str, subject: str, body: str,
               attachment: bytes | None = None, attachment_filename: str = "") -> str:
    """메일 발송. 첨부파일 있으면 함께 발송. 발송된 Message-ID 반환."""
    import email.mime.multipart
    import email.mime.text
    import email.mime.base
    import email.encoders

    creds = get_credentials()
    if not creds:
        raise RuntimeError("Gmail 미연결")

    if attachment:
        msg = email.mime.multipart.MIMEMultipart()
        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
        part = email.mime.base.MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        email.encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
        msg.attach(part)
    else:
        msg = email.mime.text.MIMEText(body, "plain", "utf-8")

    msg["to"]      = to
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service  = build("gmail", "v1", credentials=creds)
    result   = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("메일 발송 완료 → %s (id: %s)", to, result.get("id"))
    return result.get("id", "")


def get_attachment(message_id: str, attachment_id: str) -> tuple[bytes, str]:
    """첨부파일 데이터 반환 (bytes, mime_type)"""
    creds = get_credentials()
    if not creds:
        raise RuntimeError("Gmail 미연결")
    service = build("gmail", "v1", credentials=creds)
    att = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    data = base64.urlsafe_b64decode(att["data"])
    # mime type는 attachment_id만으론 모르므로 호출자가 넘겨줌
    return data
