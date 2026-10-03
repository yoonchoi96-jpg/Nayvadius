import sqlite3
from pathlib import Path
from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, content_hash TEXT NOT NULL,
 source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS results (
 document_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS entities (
 name TEXT NOT NULL, entity_type TEXT NOT NULL, confidence REAL NOT NULL,
 PRIMARY KEY(name, entity_type)
);
CREATE TABLE IF NOT EXISTS document_entities (
 document_id TEXT NOT NULL, entity_name TEXT NOT NULL, entity_type TEXT NOT NULL,
 PRIMARY KEY(document_id, entity_name, entity_type)
);
CREATE TABLE IF NOT EXISTS relations (
 source_name TEXT NOT NULL, relation TEXT NOT NULL, target_name TEXT NOT NULL,
 PRIMARY KEY(source_name, relation, target_name)
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
);
"""

def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = Path(path or settings.state_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn
