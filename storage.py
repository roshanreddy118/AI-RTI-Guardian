"""Storage layer for AI RTI Guardian.

Uses Postgres (Neon on Vercel) when DATABASE_URL is set, else a local SQLite file.
Vercel's filesystem is ephemeral, so durable tracking needs an external DB; SQLite is
kept as the zero-config local/dev + test backend.

The dialect differences — placeholder (%s vs ?), auto-id (RETURNING vs lastrowid),
dict rows — are contained here so the endpoints stay backend-agnostic.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_PATH = Path(__file__).parent / "rti.db"

COLUMNS = ("id", "created_at", "subject", "authority", "body",
           "sensitivity", "filed_on", "deadline_on", "status", "response_text")


def _connect():
    if IS_PG:
        import psycopg  # imported lazily so local/test runs need no driver
        return psycopg.connect(DATABASE_URL)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    id_col = "id SERIAL PRIMARY KEY" if IS_PG else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    ddl = f"""CREATE TABLE IF NOT EXISTS requests (
        {id_col},
        created_at TEXT NOT NULL,
        subject TEXT NOT NULL,
        authority TEXT NOT NULL,
        body TEXT NOT NULL,
        sensitivity TEXT NOT NULL,
        filed_on TEXT NOT NULL,
        deadline_on TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'filed',
        response_text TEXT
    )"""
    with _connect() as conn:
        conn.execute(ddl)
        if IS_PG:
            conn.commit()


def insert_request(created_at, subject, authority, body, sensitivity,
                   filed_on, deadline_on) -> int:
    vals = (created_at, subject, authority, body, sensitivity, filed_on, deadline_on)
    cols = "(created_at, subject, authority, body, sensitivity, filed_on, deadline_on)"
    with _connect() as conn:
        if IS_PG:
            cur = conn.execute(
                f"INSERT INTO requests {cols} VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", vals)
            new_id = cur.fetchone()[0]
            conn.commit()
            return new_id
        cur = conn.execute(
            f"INSERT INTO requests {cols} VALUES (?,?,?,?,?,?,?)", vals)
        return cur.lastrowid


def all_requests() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
    # Normalise to dicts regardless of backend (psycopg tuples vs sqlite3.Row).
    if IS_PG:
        return [dict(zip(COLUMNS, r)) for r in rows]
    return [dict(r) for r in rows]


def mark_analyzed(request_id: int, response_text: str) -> None:
    ph = "%s" if IS_PG else "?"
    with _connect() as conn:
        conn.execute(
            f"UPDATE requests SET response_text={ph}, status='analyzed' WHERE id={ph}",
            (response_text, request_id))
        if IS_PG:
            conn.commit()
