"""
storage.py — Persistence on SQLite + raw JSONL for audit trail.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from models import ScrapedItem

RAW_DIR = Path("raw")
DB_PATH = Path("results.db")


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Creates the database and the table if they do not exist."""
    RAW_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id      TEXT NOT NULL,
            keyword       TEXT NOT NULL,
            language      TEXT NOT NULL DEFAULT 'IT',
            category_l1   TEXT DEFAULT '',
            category_l2   TEXT DEFAULT '',
            query_type    TEXT DEFAULT 'generic',
            title         TEXT,
            price_raw     TEXT,
            price_value   REAL,
            currency      TEXT,
            seller        TEXT,
            rating        REAL,
            reviews_count INTEGER,
            url           TEXT,
            image_url     TEXT,
            position      INTEGER,
            scraped_at    TEXT NOT NULL,
            run_id        TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword     ON products(keyword)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_query_id    ON products(query_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scraped_at  ON products(scraped_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category_l1 ON products(category_l1)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category_l2 ON products(category_l2)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_language    ON products(language)")
    # Deduplication: prevent double-import of the same Apify run.
    # run_id is unique per Apify execution; position is unique within a run.
    # Skipped silently if the DB already has duplicates that would violate it.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_run_pos "
            "ON products(run_id, position) WHERE run_id != ''"
        )
    except Exception:
        pass
    conn.commit()
    return conn


def save_items(
    items: list[ScrapedItem],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Saves the items to SQLite and writes the raw JSONL."""
    own_conn = conn is None
    if own_conn:
        conn = init_db()

    # JSONL raw (audit trail)
    if items:
        run_id = items[0].run_id or "unknown"
        jsonl_path = RAW_DIR / f"{run_id}.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    # SQLite
    rows = [
        (
            item.query_id, item.keyword, item.language,
            item.category_l1, item.category_l2, item.query_type,
            item.title, item.price_raw, item.price_value, item.currency,
            item.seller, item.rating, item.reviews_count,
            item.url, item.image_url, item.position,
            item.scraped_at, item.run_id,
        )
        for item in items
    ]
    _before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO products
            (query_id, keyword, language,
             category_l1, category_l2, query_type,
             title, price_raw, price_value, currency,
             seller, rating, reviews_count,
             url, image_url, position,
             scraped_at, run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    inserted = conn.total_changes - _before
    conn.commit()

    if own_conn:
        conn.close()

    return inserted


def query_db(
    sql: str,
    params: tuple = (),
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Runs a SELECT query and returns a list of dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(sql, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results
