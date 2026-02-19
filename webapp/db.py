"""SQLite database setup and helpers."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "wallpeepo.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS images (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT UNIQUE NOT NULL,
            username    TEXT NOT NULL,
            date        TEXT,
            tweet_id    TEXT,
            title       TEXT,
            score       REAL DEFAULT 1500.0,
            votes_up    INTEGER DEFAULT 0,
            votes_down  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS votes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id    INTEGER NOT NULL REFERENCES images(id),
            direction   TEXT NOT NULL CHECK(direction IN ('left', 'right')),
            session_id  TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_votes_image ON votes(image_id);
        CREATE INDEX IF NOT EXISTS idx_votes_session ON votes(session_id);
        CREATE INDEX IF NOT EXISTS idx_images_score ON images(score DESC);
    """)
    conn.commit()
    conn.close()


def load_metadata_into_db(metadata: dict):
    """Bulk-insert images from metadata.json, skipping existing."""
    conn = get_db()
    cursor = conn.cursor()
    inserted = 0
    for filename, info in metadata.items():
        try:
            cursor.execute(
                """INSERT OR IGNORE INTO images (filename, username, date, tweet_id, title)
                   VALUES (?, ?, ?, ?, ?)""",
                (filename, info["username"], info.get("date"), info.get("tweet_id"), info.get("title")),
            )
            if cursor.rowcount:
                inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return inserted
