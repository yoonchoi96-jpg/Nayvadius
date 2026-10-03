import json, sqlite3
from pathlib import Path
from .config import settings
SCHEMA="""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS results(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entities(name TEXT NOT NULL,entity_type TEXT NOT NULL,aliases TEXT,confidence REAL NOT NULL,PRIMARY KEY(name,entity_type));CREATE TABLE IF NOT EXISTS document_entities(document_id TEXT NOT NULL,entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,entity_name,entity_type));CREATE TABLE IF NOT EXISTS relations(source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(source_name,relation,target_name));CREATE TABLE IF NOT EXISTS llm_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL);"""
def connect(path=None):
 p=Path(path or settings.state_path); p.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(p); c.executescript(SCHEMA); return c
def cache_get(key):
 with connect() as c:
  row=c.execute('SELECT payload FROM llm_cache WHERE cache_key=?',(key,)).fetchone(); return json.loads(row[0]) if row else None
def cache_put(key,payload):
 with connect() as c: c.execute('INSERT OR REPLACE INTO llm_cache VALUES(?,?)',(key,json.dumps(payload,ensure_ascii=False)))
def status():
 with connect() as c: return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('documents','entities','relations','llm_cache')}
