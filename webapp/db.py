"""SQLite database setup and helpers."""

import sqlite3
from pathlib import Path

_VOLUME_PATH = Path("/data/wallpeepo.db")
DB_PATH = _VOLUME_PATH if _VOLUME_PATH.parent.exists() else Path(__file__).resolve().parent / "wallpeepo.db"


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
            votes_down  INTEGER DEFAULT 0,
            votes_super INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS votes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id    INTEGER NOT NULL REFERENCES images(id),
            direction   TEXT NOT NULL CHECK(direction IN ('left', 'right', 'super')),
            session_id  TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_votes_image ON votes(image_id);
        CREATE INDEX IF NOT EXISTS idx_votes_session ON votes(session_id);
        CREATE INDEX IF NOT EXISTS idx_images_score ON images(score DESC);
    """)
    # Migrate older DBs that lack votes_super
    try:
        conn.execute("ALTER TABLE images ADD COLUMN votes_super INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Migrate votes table to accept 'super' direction
    old_schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='votes'").fetchone()
    if old_schema and "'super'" not in old_schema[0]:
        conn.executescript("""
            ALTER TABLE votes RENAME TO votes_old;
            CREATE TABLE votes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id    INTEGER NOT NULL REFERENCES images(id),
                direction   TEXT NOT NULL CHECK(direction IN ('left', 'right', 'super')),
                session_id  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO votes SELECT * FROM votes_old;
            DROP TABLE votes_old;
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
