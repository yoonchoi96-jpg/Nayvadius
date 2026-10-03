import json, sqlite3
from pathlib import Path
from .config import settings

SCHEMA="""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS results(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entities(name TEXT NOT NULL,entity_type TEXT NOT NULL,aliases TEXT,confidence REAL NOT NULL,PRIMARY KEY(name,entity_type));CREATE TABLE IF NOT EXISTS document_entities(document_id TEXT NOT NULL,entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,entity_name,entity_type));CREATE TABLE IF NOT EXISTS relations(source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(source_name,relation,target_name));CREATE TABLE IF NOT EXISTS document_relations(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,source_name,relation,target_name));CREATE TABLE IF NOT EXISTS evidence(document_id TEXT PRIMARY KEY,source TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,url TEXT,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS relation_evidence(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,evidence_document_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'checked',checked_at TEXT,PRIMARY KEY(document_id,source_name,relation,target_name,evidence_document_id));CREATE TABLE IF NOT EXISTS llm_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entity_aliases(alias TEXT PRIMARY KEY,canonical_name TEXT NOT NULL,entity_type TEXT NOT NULL);"""

def connect(path=None):
 p=Path(path or settings.state_path); p.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(p,timeout=30); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000"); c.execute("PRAGMA foreign_keys=ON"); c.executescript(SCHEMA)
 rows=c.execute("SELECT name,entity_type,aliases FROM entities").fetchall()
 for name,entity_type,aliases in rows:
  values=[name]+[x.strip() for x in (aliases or "").split(",") if x.strip()]
  for value in values:
   c.execute("INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",(value.strip().casefold(),name,entity_type))
 return c

def cache_get(key):
 with connect() as c:
  row=c.execute('SELECT payload FROM llm_cache WHERE cache_key=?',(key,)).fetchone(); return json.loads(row[0]) if row else None

def cache_put(key,payload):
 with connect() as c: c.execute('INSERT OR REPLACE INTO llm_cache VALUES(?,?)',(key,json.dumps(payload,ensure_ascii=False)))

def save_evidence(evidence):
 with connect() as c:
  c.execute('INSERT OR REPLACE INTO evidence(document_id,source,title,content,url) VALUES(?,?,?,?,?)',(evidence.document_id,evidence.source,evidence.title,evidence.content,evidence.url))

def link_relation_evidence(document_id,source_name,relation,target_name,evidence_document_id,status='checked'):
 if status not in ('checked','contradicted','unverified'): raise ValueError('invalid evidence status: '+status)
 with connect() as c:
  c.execute('INSERT OR REPLACE INTO relation_evidence(document_id,source_name,relation,target_name,evidence_document_id,status,checked_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)',(document_id,source_name,relation,target_name,evidence_document_id,status))

def save_entity_alias(alias, canonical_name, entity_type):
 with connect() as c:
  c.execute('INSERT OR REPLACE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)',(alias,canonical_name,entity_type))

def status():
 with connect() as c: return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('documents','entities','relations','document_relations','evidence','relation_evidence','entity_aliases','llm_cache')}


def merge_entity(canonical_name, duplicate_name, entity_type):
 with connect() as db:
  if canonical_name == duplicate_name:
   return False
  keep = db.execute("SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?", (canonical_name,entity_type)).fetchone()
  dup = db.execute("SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?", (duplicate_name,entity_type)).fetchone()
  if not dup:
   return False
  aliases = set(x.strip() for x in ((keep[0] if keep else "") or "").split(",") if x.strip())
  aliases.update(x.strip() for x in ((dup[0] or "")).split(",") if x.strip())
  aliases.discard(canonical_name)
  aliases.add(duplicate_name)
  confidence = max(float(keep[1]) if keep else 0.0, float(dup[1]))
  db.execute("INSERT INTO entities(name,entity_type,aliases,confidence) VALUES(?,?,?,?) ON CONFLICT(name,entity_type) DO UPDATE SET aliases=excluded.aliases,confidence=excluded.confidence",
             (canonical_name,entity_type,",".join(sorted(aliases,key=lambda x:(x.casefold(),x))),confidence))
  db.execute("UPDATE document_entities SET entity_name=? WHERE entity_name=? AND entity_type=?", (canonical_name,duplicate_name,entity_type))
  db.execute("UPDATE relations SET source_name=? WHERE source_name=?", (canonical_name,duplicate_name))
  db.execute("UPDATE relations SET target_name=? WHERE target_name=?", (canonical_name,duplicate_name))
  db.execute("UPDATE document_relations SET source_name=? WHERE source_name=?", (canonical_name,duplicate_name))
  db.execute("UPDATE document_relations SET target_name=? WHERE target_name=?", (canonical_name,duplicate_name))
  db.execute("UPDATE relation_evidence SET source_name=? WHERE source_name=?", (canonical_name,duplicate_name))
  db.execute("UPDATE relation_evidence SET target_name=? WHERE target_name=?", (canonical_name,duplicate_name))
  db.execute("DELETE FROM entity_aliases WHERE canonical_name=? AND entity_type=?", (duplicate_name,entity_type))
  db.execute("INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)", (canonical_name.casefold(),canonical_name,entity_type))
  for alias in aliases:
   db.execute("INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)", (alias.casefold(),canonical_name,entity_type))
  db.execute("DELETE FROM entities WHERE name=? AND entity_type=?", (duplicate_name,entity_type))
  db.execute("""DELETE FROM relations WHERE rowid NOT IN (
      SELECT MIN(rowid) FROM relations GROUP BY source_name,relation,target_name
  )""")
  db.execute("""DELETE FROM document_relations WHERE rowid NOT IN (
      SELECT MIN(rowid) FROM document_relations GROUP BY document_id,source_name,relation,target_name
  )""")
  db.execute("""DELETE FROM relation_evidence WHERE rowid NOT IN (
      SELECT MIN(rowid) FROM relation_evidence
      GROUP BY document_id,source_name,relation,target_name,evidence_document_id
  )""")
  return True
