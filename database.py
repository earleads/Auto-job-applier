"""
Database layer — SQLite for tracking jobs, applications, and status.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from config import DB_PATH


def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_add_column(conn, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't already exist."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            company         TEXT NOT NULL,
            location        TEXT,
            url             TEXT UNIQUE NOT NULL,
            apply_url       TEXT,
            description     TEXT,
            source          TEXT,
            posted_at       TEXT,
            scraped_at      TEXT NOT NULL,
            match_score     INTEGER,
            status          TEXT DEFAULT 'new',
            ats_type        TEXT
        );

        CREATE TABLE IF NOT EXISTS applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id          TEXT NOT NULL REFERENCES jobs(id),
            applied_at      TEXT NOT NULL,
            cv_path         TEXT,
            cover_letter_path TEXT,
            status          TEXT DEFAULT 'submitted',
            notes           TEXT,
            follow_up_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date            TEXT PRIMARY KEY,
            scraped         INTEGER DEFAULT 0,
            matched         INTEGER DEFAULT 0,
            applied         INTEGER DEFAULT 0,
            failed          INTEGER DEFAULT 0
        );
    """)

    # Migrations: add columns that may not exist in older databases
    _migrate_add_column(conn, "jobs", "apply_url", "TEXT")
    _migrate_add_column(conn, "jobs", "ats_type", "TEXT")
    _migrate_add_column(conn, "jobs", "retry_count", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()
    print("✅ Database initialized")


def is_first_scrape() -> bool:
    """Return True if no jobs have been scraped yet (first run)."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0] == 0
    finally:
        conn.close()


def upsert_job(job: dict) -> bool:
    """Insert a job. Returns True if it's new, False if already seen."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO jobs (id, title, company, location, url, apply_url, description,
                              source, posted_at, scraped_at, ats_type)
            VALUES (:id, :title, :company, :location, :url, :apply_url, :description,
                    :source, :posted_at, :scraped_at, :ats_type)
        """, {**job, "apply_url": job.get("apply_url", ""), "scraped_at": datetime.now(timezone.utc).isoformat()})
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Already exists
    finally:
        conn.close()


def update_job_score(job_id: str, score: int):
    conn = get_conn()
    conn.execute("UPDATE jobs SET match_score = ?, status = 'scored' WHERE id = ?",
                 (score, job_id))
    conn.commit()
    conn.close()


def update_job_status(job_id: str, status: str):
    conn = get_conn()
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    conn.close()


def log_application(job_id: str, cv_path: str, cover_letter_path: str, notes: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO applications (job_id, applied_at, cv_path, cover_letter_path, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (job_id, datetime.now(timezone.utc).isoformat(), cv_path, cover_letter_path, notes))
    conn.commit()
    conn.close()


def increment_retry(job_id: str, max_retries: int = 2) -> bool:
    """Increment retry count. Returns True if job should be skipped (exceeded max)."""
    conn = get_conn()
    conn.execute("UPDATE jobs SET retry_count = COALESCE(retry_count, 0) + 1 WHERE id = ?", (job_id,))
    conn.commit()
    row = conn.execute("SELECT retry_count FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row and (row[0] or 0) > max_retries:
        update_job_status(job_id, "skipped")
        return True
    return False


def get_jobs_by_status(status: str) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM jobs WHERE status = ?", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_today_applications() -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE applied_at LIKE ?", (f"{today}%",)
    ).fetchone()[0]
    conn.close()
    return count


def get_stats() -> dict:
    conn = get_conn()
    stats = {
        "total_scraped": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "matched": conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('matched','applied')").fetchone()[0],
        "applied": conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scored'").fetchone()[0],
        "captcha_blocked": conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'captcha_blocked'").fetchone()[0],
    }
    conn.close()
    return stats
