"""Хранилище распознанных отчётов (SQLite)."""
import json
import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "./reports.db")

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
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def save_report(chat_id: int, message_id: int, user_name: str, text: str,
                result: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM reports WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        conn.execute(
            "INSERT INTO reports (chat_id, message_id, user_name, date, text,"
            " total, has_errors, errors_json, summary)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                message_id,
                user_name,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                text,
                result.get("total"),
                1 if result.get("has_errors") else 0,
                json.dumps(result.get("errors") or [], ensure_ascii=False),
                result.get("summary") or "",
            ),
        )


def get_reports(chat_id: int, days: int) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE chat_id = ? AND date >= ?"
            " ORDER BY date",
            (chat_id, since),
        ).fetchall()
    return [dict(r) for r in rows]
