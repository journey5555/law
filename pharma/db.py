import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE   = _BASE_DIR / "data" / "pharma.db"


def init_db() -> None:
    DB_FILE.parent.mkdir(exist_ok=True)
    with get_conn() as conn:
        # 기존 DB 컬럼 마이그레이션
        cols = {r[1] for r in conn.execute("PRAGMA table_info(attachment_hashes)").fetchall()}
        if "knowledge_id" not in cols:
            try:
                conn.execute("ALTER TABLE attachment_hashes ADD COLUMN knowledge_id TEXT")
            except Exception:
                pass
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS drugs (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            description    TEXT,
            expected_date  TEXT,
            sender_filter  TEXT,
            keyword_filter TEXT,
            created_at     TEXT NOT NULL,
            status         TEXT DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS results (
            id               TEXT PRIMARY KEY,
            drug_id          TEXT,
            email_message_id TEXT UNIQUE,
            sender           TEXT,
            subject          TEXT,
            received_at      TEXT,
            summary          TEXT,
            raw_body         TEXT,
            created_at       TEXT NOT NULL,
            FOREIGN KEY (drug_id) REFERENCES drugs(id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id         TEXT PRIMARY KEY,
            drug_id    TEXT,
            alert_type TEXT,
            message    TEXT,
            created_at TEXT NOT NULL,
            read       INTEGER DEFAULT 0,
            FOREIGN KEY (drug_id) REFERENCES drugs(id)
        );
        CREATE TABLE IF NOT EXISTS attachment_hashes (
            sha256        TEXT PRIMARY KEY,
            doc_id        TEXT NOT NULL,
            filename      TEXT,
            saved_at      TEXT NOT NULL,
            knowledge_id  TEXT
        );
        CREATE TABLE IF NOT EXISTS send_history (
            id            TEXT PRIMARY KEY,
            doc_id        TEXT NOT NULL,
            filename      TEXT,
            sent_to       TEXT NOT NULL,
            subject       TEXT,
            sent_at       TEXT NOT NULL,
            extracted_json TEXT
        );
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return str(uuid.uuid4())[:8]
