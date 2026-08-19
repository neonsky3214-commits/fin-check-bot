"""Хранилище распознанных отчётов (SQLite)."""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.getenv("DB_PATH", "./reports.db")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    date TEXT NOT NULL,
    text TEXT NOT NULL,
    total REAL,
    has_errors INTEGER NOT NULL,
    errors_json TEXT,
    summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_chat_date ON reports (chat_id, date);
CREATE TABLE IF NOT EXISTS sched_sent (
    kind TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (kind, chat_id, date)
);
"""

_EXTRA_COLUMNS = ("income", "expenses", "cash", "kassa", "safe")


def now() -> datetime:
    """Текущее время в рабочем часовом поясе (наивное, для хранения)."""
    return datetime.now(TZ).replace(tzinfo=None)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        for col in _EXTRA_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE reports ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass  # колонка уже есть


def save_report(chat_id: int, message_id: int, user_name: str, text: str,
                result: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM reports WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        conn.execute(
            "INSERT INTO reports (chat_id, message_id, user_name, date, text,"
            " total, has_errors, errors_json, summary,"
            " income, expenses, cash, kassa, safe)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                message_id,
                user_name,
                now().strftime("%Y-%m-%d %H:%M"),
                text,
                result.get("total"),
                1 if result.get("has_errors") else 0,
                json.dumps(result.get("errors") or [], ensure_ascii=False),
                result.get("summary") or "",
                result.get("income"),
                result.get("expenses"),
                result.get("cash"),
                result.get("kassa"),
                result.get("safe"),
            ),
        )


def get_reports(chat_id: int, days: int) -> list[dict]:
    since = (now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE chat_id = ? AND date >= ?"
            " ORDER BY date",
            (chat_id, since),
        ).fetchall()
    return [dict(r) for r in rows]


def get_previous_reports(chat_id: int, exclude_message_id: int,
                         limit: int = 8) -> list[dict]:
    """Последние отчёты чата (новые первыми), без текущего сообщения."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE chat_id = ? AND message_id != ?"
            " ORDER BY date DESC, id DESC LIMIT ?",
            (chat_id, exclude_message_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_chats() -> list[int]:
    """Чаты, в которых когда-либо были отчёты."""
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT chat_id FROM reports").fetchall()
    return [r["chat_id"] for r in rows]


def has_report_since(chat_id: int, since: datetime) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM reports WHERE chat_id = ? AND date >= ? LIMIT 1",
            (chat_id, since.strftime("%Y-%m-%d %H:%M")),
        ).fetchone()
    return row is not None


def try_mark_sent(kind: str, chat_id: int, date: str) -> bool:
    """True, если событие (kind, chat_id, date) ещё не отправлялось."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sched_sent (kind, chat_id, date)"
            " VALUES (?, ?, ?)",
            (kind, chat_id, date),
        )
        return cur.rowcount > 0
