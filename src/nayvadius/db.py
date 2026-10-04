import json, sqlite3
from pathlib import Path
from .config import settings

SCHEMA="""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS results(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entities(name TEXT NOT NULL,entity_type TEXT NOT NULL,aliases TEXT,confidence REAL NOT NULL,PRIMARY KEY(name,entity_type));CREATE TABLE IF NOT EXISTS document_entities(document_id TEXT NOT NULL,entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,entity_name,entity_type));CREATE TABLE IF NOT EXISTS relations(source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(source_name,relation,target_name));CREATE TABLE IF NOT EXISTS document_relations(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,source_name,relation,target_name));CREATE TABLE IF NOT EXISTS evidence(document_id TEXT PRIMARY KEY,source TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,url TEXT,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS relation_evidence(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,evidence_document_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'checked',checked_at TEXT,PRIMARY KEY(document_id,source_name,relation,target_name,evidence_document_id));CREATE TABLE IF NOT EXISTS llm_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entity_aliases(alias TEXT PRIMARY KEY,canonical_name TEXT NOT NULL,entity_type TEXT NOT NULL);CREATE TABLE IF NOT EXISTS processing_failures(document_id TEXT PRIMARY KEY,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL,next_retry_at TEXT,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS vocabularies(id TEXT PRIMARY KEY,word TEXT NOT NULL,traditional TEXT,pinyin TEXT,pos TEXT,meaning_ko TEXT,hsk_levels TEXT,wordbooks TEXT,source TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS entity_vocabulary_links(entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,vocabulary_id TEXT NOT NULL,match_type TEXT NOT NULL DEFAULT 'explicit',confidence REAL NOT NULL DEFAULT 1.0,PRIMARY KEY(entity_name,entity_type,vocabulary_id));"""

def connect(path=None):
 p=Path(path or settings.state_path); p.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(p,timeout=30); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000"); c.execute("PRAGMA foreign_keys=ON"); c.executescript(SCHEMA)
 rows=c.execute("SELECT name,entity_type,aliases FROM entities").fetchall()
 for name,entity_type,aliases in rows:
  for value in [name]+[x.strip() for x in (aliases or "").split(",") if x.strip()]:
   c.execute("INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",(value.strip().casefold(),name,entity_type))
 return c

def cache_get(key):
 with connect() as c:
  row=c.execute('SELECT payload FROM llm_cache WHERE cache_key=?',(key,)).fetchone(); return json.loads(row[0]) if row else None

def cache_put(key,payload):
 with connect() as c: c.execute('INSERT OR REPLACE INTO llm_cache VALUES(?,?)',(key,json.dumps(payload,ensure_ascii=False)))

def save_evidence(evidence):
 with connect() as c: c.execute('INSERT OR REPLACE INTO evidence(document_id,source,title,content,url) VALUES(?,?,?,?,?)',(evidence.document_id,evidence.source,evidence.title,evidence.content,evidence.url))

def link_relation_evidence(document_id,source_name,relation,target_name,evidence_document_id,status='checked'):
 if status not in ('checked','contradicted','unverified'): raise ValueError('invalid evidence status: '+status)
 with connect() as c: c.execute('INSERT OR REPLACE INTO relation_evidence(document_id,source_name,relation,target_name,evidence_document_id,status,checked_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)',(document_id,source_name,relation,target_name,evidence_document_id,status))

def save_entity_alias(alias, canonical_name, entity_type):
 with connect() as c: c.execute('INSERT OR REPLACE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)',(alias,canonical_name,entity_type))

def record_failure(document_id, error, max_attempts=5):
 with connect() as c:
  row=c.execute("SELECT attempts FROM processing_failures WHERE document_id=?",(document_id,)).fetchone()
  attempts=min((row[0] if row else 0)+1,max_attempts)
  c.execute("INSERT INTO processing_failures(document_id,attempts,last_error,next_retry_at,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(document_id) DO UPDATE SET attempts=excluded.attempts,last_error=excluded.last_error,next_retry_at=excluded.next_retry_at,updated_at=CURRENT_TIMESTAMP",
            (document_id,attempts,str(error)[:4000],None))

def clear_failure(document_id):
 with connect() as c: c.execute("DELETE FROM processing_failures WHERE document_id=?",(document_id,))

def failed_document_ids(max_attempts=5):
 with connect() as c: return [r[0] for r in c.execute("SELECT document_id FROM processing_failures WHERE attempts < ? ORDER BY updated_at",(max_attempts,)).fetchall()]

def prune_orphan_entities():
 with connect() as db:
  rows=db.execute("SELECT name,entity_type FROM entities WHERE NOT EXISTS (SELECT 1 FROM document_entities de WHERE de.entity_name=entities.name AND de.entity_type=entities.entity_type) AND NOT EXISTS (SELECT 1 FROM relations r WHERE r.source_name=entities.name OR r.target_name=entities.name)").fetchall()
  for name,entity_type in rows:
   db.execute("DELETE FROM entity_aliases WHERE canonical_name=? AND entity_type=?",(name,entity_type)); db.execute("DELETE FROM entities WHERE name=? AND entity_type=?",(name,entity_type))
  return len(rows)

def save_vocabulary(vocabulary, entity_links=()):
    """Persist one Abel vocabulary record and its current entity links."""
    with connect() as db:
        db.execute(
            "INSERT INTO vocabularies(id,word,traditional,pinyin,pos,meaning_ko,hsk_levels,wordbooks,source,metadata,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(id) DO UPDATE SET word=excluded.word,traditional=excluded.traditional,pinyin=excluded.pinyin,pos=excluded.pos,meaning_ko=excluded.meaning_ko,hsk_levels=excluded.hsk_levels,wordbooks=excluded.wordbooks,source=excluded.source,metadata=excluded.metadata,updated_at=CURRENT_TIMESTAMP",
            (vocabulary.id,vocabulary.word,vocabulary.traditional,vocabulary.pinyin,vocabulary.pos,vocabulary.meaning_ko,
             "|".join(vocabulary.hsk_levels),"|".join(vocabulary.wordbooks),vocabulary.source,
             json.dumps(vocabulary.metadata,ensure_ascii=False))
        )
        db.execute("DELETE FROM entity_vocabulary_links WHERE vocabulary_id=?",(vocabulary.id,))
        for name,entity_type,match_type,confidence in entity_links:
            db.execute("INSERT OR REPLACE INTO entity_vocabulary_links VALUES(?,?,?,?,?)",
                       (name,entity_type,vocabulary.id,match_type,confidence))


def vocabulary_links(vocabulary_id=None):
 with connect() as c:
  if vocabulary_id:
   return c.execute("SELECT entity_name,entity_type,match_type,confidence FROM entity_vocabulary_links WHERE vocabulary_id=? ORDER BY confidence DESC,entity_name",(vocabulary_id,)).fetchall()
  return c.execute("SELECT entity_name,entity_type,vocabulary_id,match_type,confidence FROM entity_vocabulary_links ORDER BY entity_name,vocabulary_id").fetchall()

def status():
 with connect() as c: return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('documents','entities','relations','document_relations','evidence','relation_evidence','entity_aliases','llm_cache','processing_failures','vocabularies','entity_vocabulary_links')}

def merge_entity(canonical_name, duplicate_name, entity_type):
 with connect() as db:
  if canonical_name==duplicate_name: return False
  keep=db.execute("SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?",(canonical_name,entity_type)).fetchone()
  dup=db.execute("SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?",(duplicate_name,entity_type)).fetchone()
  if not dup: return False
  aliases=set(x.strip() for x in ((keep[0] if keep else "") or "").split(",") if x.strip()); aliases.update(x.strip() for x in (dup[0] or "").split(",") if x.strip()); aliases.discard(canonical_name); aliases.add(duplicate_name)
  confidence=max(float(keep[1]) if keep else 0.0,float(dup[1]))
  db.execute("INSERT INTO entities(name,entity_type,aliases,confidence) VALUES(?,?,?,?) ON CONFLICT(name,entity_type) DO UPDATE SET aliases=excluded.aliases,confidence=excluded.confidence",(canonical_name,entity_type,",".join(sorted(aliases,key=lambda x:(x.casefold(),x))),confidence))
  db.execute("UPDATE document_entities SET entity_name=? WHERE entity_name=? AND entity_type=?",(canonical_name,duplicate_name,entity_type))
  rels=db.execute("SELECT source_name,relation,target_name,confidence FROM relations WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name)).fetchall(); db.execute("DELETE FROM relations WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name))
  for source,relation,target,conf in rels:
   source=canonical_name if source==duplicate_name else source; target=canonical_name if target==duplicate_name else target
   existing=db.execute("SELECT confidence FROM relations WHERE source_name=? AND relation=? AND target_name=?",(source,relation,target)).fetchone()
   if existing: db.execute("UPDATE relations SET confidence=MAX(confidence,?) WHERE source_name=? AND relation=? AND target_name=?",(conf,source,relation,target))
   else: db.execute("INSERT INTO relations VALUES(?,?,?,?)",(source,relation,target,conf))
  doc_rels=db.execute("SELECT document_id,source_name,relation,target_name,confidence FROM document_relations WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name)).fetchall(); db.execute("DELETE FROM document_relations WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name))
  for document_id,source,relation,target,conf in doc_rels:
   source=canonical_name if source==duplicate_name else source; target=canonical_name if target==duplicate_name else target
   existing=db.execute("SELECT confidence FROM document_relations WHERE document_id=? AND source_name=? AND relation=? AND target_name=?",(document_id,source,relation,target)).fetchone()
   if existing: db.execute("UPDATE document_relations SET confidence=MAX(confidence,?) WHERE document_id=? AND source_name=? AND relation=? AND target_name=?",(conf,document_id,source,relation,target))
   else: db.execute("INSERT INTO document_relations VALUES(?,?,?,?,?)",(document_id,source,relation,target,conf))
  evidence=db.execute("SELECT document_id,source_name,relation,target_name,evidence_document_id,status,checked_at FROM relation_evidence WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name)).fetchall(); db.execute("DELETE FROM relation_evidence WHERE source_name=? OR target_name=?",(duplicate_name,duplicate_name))
  for document_id,source,relation,target,evidence_document_id,status,checked_at in evidence:
   source=canonical_name if source==duplicate_name else source; target=canonical_name if target==duplicate_name else target
   db.execute("INSERT OR REPLACE INTO relation_evidence(document_id,source_name,relation,target_name,evidence_document_id,status,checked_at) VALUES(?,?,?,?,?,?,?)",(document_id,source,relation,target,evidence_document_id,status,checked_at))
  db.execute("DELETE FROM entity_aliases WHERE canonical_name=? AND entity_type=?",(duplicate_name,entity_type))
  for alias in aliases: db.execute("INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",(alias.casefold(),canonical_name,entity_type))
  db.execute("DELETE FROM entities WHERE name=? AND entity_type=?",(duplicate_name,entity_type)); return True
