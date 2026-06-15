import base64
import hashlib
import json
import logging
import secrets
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import PHARMA_GMAIL_REDIRECT_URI, PHARMA_GMAIL_SCOPES

logger = logging.getLogger("pharma.gmail")

_BASE_DIR        = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = _BASE_DIR / "credentials" / "pharma_client_secret.json"
TOKEN_FILE       = _BASE_DIR / "credentials" / "pharma_token.json"
_PKCE_FILE       = _BASE_DIR / "credentials" / "pharma_pkce.json"


def _pkce_pair() -> tuple[str, str]:
    verifier  = secrets.token_urlsafe(96)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def get_auth_url() -> str:
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE), scopes=PHARMA_GMAIL_SCOPES, redirect_uri=PHARMA_GMAIL_REDIRECT_URI
    )
    code_verifier, code_challenge = _pkce_pair()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    _PKCE_FILE.write_text(json.dumps({"verifier": code_verifier, "state": state}))
    return auth_url


def exchange_code(code: str) -> None:
    code_verifier = None
    if _PKCE_FILE.exists():
        try:
            code_verifier = json.loads(_PKCE_FILE.read_text()).get("verifier")
        finally:
            _PKCE_FILE.unlink(missing_ok=True)

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE), scopes=PHARMA_GMAIL_SCOPES, redirect_uri=PHARMA_GMAIL_REDIRECT_URI
    )
    flow.fetch_token(code=code, code_verifier=code_verifier)
    TOKEN_FILE.write_text(flow.credentials.to_json())
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
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id":      msg["id"],
        "sender":  headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date":    headers.get("date", ""),
        "body":    _extract_body(msg.get("payload", {})),
    }


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        if mime.startswith("multipart/"):
            text = _extract_body(part)
            if text:
                return text
    return ""
