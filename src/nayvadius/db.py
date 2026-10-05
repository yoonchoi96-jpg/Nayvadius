import json, sqlite3
from pathlib import Path
from .config import settings

SCHEMA="""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,content TEXT NOT NULL DEFAULT '');CREATE TABLE IF NOT EXISTS results(document_id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entities(name TEXT NOT NULL,entity_type TEXT NOT NULL,aliases TEXT,confidence REAL NOT NULL,PRIMARY KEY(name,entity_type));CREATE TABLE IF NOT EXISTS document_entities(document_id TEXT NOT NULL,entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,entity_name,entity_type));CREATE TABLE IF NOT EXISTS relations(source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(source_name,relation,target_name));CREATE TABLE IF NOT EXISTS document_relations(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,confidence REAL NOT NULL,PRIMARY KEY(document_id,source_name,relation,target_name));CREATE TABLE IF NOT EXISTS evidence(document_id TEXT PRIMARY KEY,source TEXT NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,url TEXT,checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS relation_evidence(document_id TEXT NOT NULL,source_name TEXT NOT NULL,relation TEXT NOT NULL,target_name TEXT NOT NULL,evidence_document_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'checked',checked_at TEXT,PRIMARY KEY(document_id,source_name,relation,target_name,evidence_document_id));CREATE TABLE IF NOT EXISTS llm_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entity_aliases(alias TEXT NOT NULL,canonical_name TEXT NOT NULL,entity_type TEXT NOT NULL,PRIMARY KEY(alias,entity_type));CREATE TABLE IF NOT EXISTS entity_sources(entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,source TEXT NOT NULL,document_id TEXT NOT NULL,PRIMARY KEY(entity_name,entity_type,source,document_id));CREATE TABLE IF NOT EXISTS entity_merge_log(id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_name TEXT NOT NULL,duplicate_name TEXT NOT NULL,entity_type TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS processing_failures(document_id TEXT PRIMARY KEY,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL,next_retry_at TEXT,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS vocabularies(id TEXT PRIMARY KEY,word TEXT NOT NULL,traditional TEXT,pinyin TEXT,pos TEXT,meaning_ko TEXT,hsk_levels TEXT,wordbooks TEXT,source TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS vocabulary_aliases(alias TEXT PRIMARY KEY,canonical_id TEXT NOT NULL);CREATE TABLE IF NOT EXISTS entity_vocabulary_links(entity_name TEXT NOT NULL,entity_type TEXT NOT NULL,vocabulary_id TEXT NOT NULL,match_type TEXT NOT NULL DEFAULT 'explicit',confidence REAL NOT NULL DEFAULT 1.0,PRIMARY KEY(entity_name,entity_type,vocabulary_id));CREATE TABLE IF NOT EXISTS document_vocabulary_links(document_id TEXT NOT NULL,vocabulary_id TEXT NOT NULL,match_type TEXT NOT NULL DEFAULT 'exact',confidence REAL NOT NULL DEFAULT 1.0,PRIMARY KEY(document_id,vocabulary_id));CREATE TABLE IF NOT EXISTS vocabulary_sources(vocabulary_id TEXT NOT NULL,source_id TEXT NOT NULL,source TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(vocabulary_id,source_id));"""

def connect(path=None):
 p=Path(path or settings.state_path); p.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(p,timeout=30); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000"); c.execute("PRAGMA foreign_keys=ON"); c.executescript(SCHEMA)
 _migrate_document_content(c)
 _migrate_entity_types(c)
 return c


def _migrate_document_content(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
    if "content" not in columns:
        db.execute("ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT ''")


def _migrate_entity_types(db):
    """Migrate legacy Companies/Brands into canonical Organizations."""
    legacy_entities = db.execute(
        "SELECT name,entity_type,aliases,confidence FROM entities WHERE entity_type IN ('Companies','Brands')"
    ).fetchall()

    # Migrate entity rows and all type-bearing provenance/link tables.
    for name, entity_type, aliases, confidence in legacy_entities:
        existing = db.execute(
            "SELECT aliases,confidence FROM entities WHERE name=? AND entity_type='Organizations'",
            (name,),
        ).fetchone()
        old_aliases = {x.strip() for x in (aliases or "").split(",") if x.strip()}
        if existing:
            merged = {x.strip() for x in (existing[0] or "").split(",") if x.strip()}
            merged.update(old_aliases)
            db.execute(
                "UPDATE entities SET aliases=?,confidence=? WHERE name=? AND entity_type='Organizations'",
                (",".join(sorted(merged, key=lambda x: (x.casefold(), x))),
                 max(float(existing[1]), float(confidence)), name),
            )
        else:
            db.execute(
                "INSERT INTO entities(name,entity_type,aliases,confidence) VALUES(?,?,?,?)",
                (name, "Organizations", aliases or "", confidence),
            )

        db.execute(
            "UPDATE OR IGNORE document_entities SET entity_type='Organizations' WHERE entity_name=? AND entity_type=?",
            (name, entity_type),
        )
        db.execute(
            "DELETE FROM document_entities WHERE entity_name=? AND entity_type=?",
            (name, entity_type),
        )
        db.execute(
            "UPDATE OR IGNORE entity_sources SET entity_type='Organizations' WHERE entity_name=? AND entity_type=?",
            (name, entity_type),
        )
        db.execute(
            "DELETE FROM entity_sources WHERE entity_name=? AND entity_type=?",
            (name, entity_type),
        )
        db.execute(
            "DELETE FROM entities WHERE name=? AND entity_type=?",
            (name, entity_type),
        )

    # Only rebuild aliases when the legacy PK/schema or legacy entity types require it.
    info = db.execute("PRAGMA table_info(entity_aliases)").fetchall()
    pk_columns = [row[1] for row in info if row[5]]
    legacy_alias_count = db.execute(
        "SELECT COUNT(*) FROM entity_aliases WHERE entity_type IN ('Companies','Brands')"
    ).fetchone()[0]
    if pk_columns == ["alias"] or legacy_alias_count:
        source_table = "entity_aliases_legacy" if pk_columns == ["alias"] else "entity_aliases_migration"
        db.execute(f"ALTER TABLE entity_aliases RENAME TO {source_table}")
        db.execute(
            "CREATE TABLE entity_aliases("
            "alias TEXT NOT NULL,canonical_name TEXT NOT NULL,entity_type TEXT NOT NULL,"
            "PRIMARY KEY(alias,entity_type))"
        )
        db.execute(
            "INSERT OR REPLACE INTO entity_aliases(alias,canonical_name,entity_type) "
            "SELECT alias,canonical_name,"
            "CASE WHEN entity_type IN ('Companies','Brands') THEN 'Organizations' ELSE entity_type END "
            f"FROM {source_table}"
        )
        db.execute(f"DROP TABLE {source_table}")

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
 with connect() as c:
  c.execute("INSERT OR REPLACE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",(alias,canonical_name,entity_type))

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

def merge_vocabulary(canonical_id, duplicate_id):
    if canonical_id == duplicate_id:
        return False
    with connect() as db:
        keep=db.execute("SELECT word,traditional,pinyin,pos,meaning_ko,hsk_levels,wordbooks,metadata FROM vocabularies WHERE id=?",(canonical_id,)).fetchone()
        dup=db.execute("SELECT word,traditional,pinyin,pos,meaning_ko,hsk_levels,wordbooks,metadata FROM vocabularies WHERE id=?",(duplicate_id,)).fetchone()
        if not dup:
            return False
        if keep:
            levels=set((keep[5] or "").split("|")) | set((dup[5] or "").split("|"))
            books=set((keep[6] or "").split("|")) | set((dup[6] or "").split("|"))
            meta=json.loads(keep[7] or "{}"); meta.update(json.loads(dup[7] or "{}"))
            db.execute("UPDATE vocabularies SET traditional=?,pinyin=?,pos=?,meaning_ko=?,hsk_levels=?,wordbooks=?,metadata=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (keep[1] or dup[1],keep[2] or dup[2],keep[3] or dup[3],keep[4] or dup[4],
                        "|".join(sorted(x for x in levels if x)), "|".join(sorted(x for x in books if x)),
                        json.dumps(meta,ensure_ascii=False),canonical_id))
            db.execute("UPDATE entity_vocabulary_links SET vocabulary_id=? WHERE vocabulary_id=?",(canonical_id,duplicate_id))
            db.execute("UPDATE document_vocabulary_links SET vocabulary_id=? WHERE vocabulary_id=?",(canonical_id,duplicate_id))
            db.execute("UPDATE vocabulary_sources SET vocabulary_id=? WHERE vocabulary_id=?",(canonical_id,duplicate_id))
            db.execute("DELETE FROM vocabularies WHERE id=?",(duplicate_id,))
        else:
            db.execute("UPDATE vocabularies SET id=? WHERE id=?",(canonical_id,duplicate_id))
        db.execute("UPDATE vocabulary_aliases SET canonical_id=? WHERE canonical_id=?",(canonical_id,duplicate_id))
        return True

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


def _norm_vocabulary_alias(value):
 return " ".join(str(value or "").strip().casefold().split())

def resolve_vocabulary_id(value):
 alias = _norm_vocabulary_alias(value)
 if not alias: return None
 with connect() as c:
  row=c.execute("SELECT canonical_id FROM vocabulary_aliases WHERE alias=?",(alias,)).fetchone()
  return row[0] if row else None

def save_vocabulary_alias(alias, canonical_id):
 alias=_norm_vocabulary_alias(alias)
 if alias:
  with connect() as c: c.execute("INSERT OR IGNORE INTO vocabulary_aliases(alias,canonical_id) VALUES(?,?)",(alias,canonical_id))

def save_vocabulary_source(vocabulary_id, source_id, source, metadata=None):
 with connect() as c:
  c.execute("INSERT OR REPLACE INTO vocabulary_sources(vocabulary_id,source_id,source,metadata) VALUES(?,?,?,?)",
            (vocabulary_id,source_id,source,json.dumps(metadata or {},ensure_ascii=False)))

def link_document_vocabularies(document_id, vocabulary_ids, match_type="exact", confidence=1.0):
 with connect() as c:
  for vocabulary_id in vocabulary_ids:
   canonical=resolve_vocabulary_id(vocabulary_id) or vocabulary_id
   c.execute("INSERT OR REPLACE INTO document_vocabulary_links VALUES(?,?,?,?)",(document_id,canonical,match_type,confidence))

def document_vocabulary_links(document_id=None):
 with connect() as c:
  if document_id:
   return c.execute("SELECT vocabulary_id,match_type,confidence FROM document_vocabulary_links WHERE document_id=? ORDER BY vocabulary_id",(document_id,)).fetchall()
  return c.execute("SELECT document_id,vocabulary_id,match_type,confidence FROM document_vocabulary_links ORDER BY document_id,vocabulary_id").fetchall()

def vocabulary_documents(vocabulary_id):
 with connect() as c:
  canonical=resolve_vocabulary_id(vocabulary_id) or vocabulary_id
  return c.execute("SELECT document_id,match_type,confidence FROM document_vocabulary_links WHERE vocabulary_id=? ORDER BY document_id",(canonical,)).fetchall()

def vocabulary_links(vocabulary_id=None):
 with connect() as c:
  if vocabulary_id:
   return c.execute("SELECT entity_name,entity_type,match_type,confidence FROM entity_vocabulary_links WHERE vocabulary_id=? ORDER BY confidence DESC,entity_name",(vocabulary_id,)).fetchall()
  return c.execute("SELECT entity_name,entity_type,vocabulary_id,match_type,confidence FROM entity_vocabulary_links ORDER BY entity_name,vocabulary_id").fetchall()

def status():
 with connect() as c: return {t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('documents','entities','relations','document_relations','evidence','relation_evidence','entity_aliases','llm_cache','processing_failures','entity_merge_log','vocabularies','vocabulary_aliases','entity_vocabulary_links')}

def log_entity_merge(canonical_name, duplicate_name, entity_type, reason):
 with connect() as db:
  db.execute("INSERT INTO entity_merge_log(canonical_name,duplicate_name,entity_type,reason) VALUES(?,?,?,?)",(canonical_name,duplicate_name,entity_type,reason))

def merge_entity(canonical_name, duplicate_name, entity_type, reason="explicit", db_path=None):
    """Conservatively merge same-type entities and retain an audit trail."""
    if not canonical_name or not duplicate_name or not entity_type:
        return False
    if canonical_name == duplicate_name:
        return False
    if reason not in ("explicit", "exact_name", "explicit_alias", "provenance_alias"):
        raise ValueError("invalid entity merge reason: " + str(reason))

    with connect(db_path) as db:
        keep = db.execute(
            "SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?",
            (canonical_name, entity_type),
        ).fetchone()
        dup = db.execute(
            "SELECT aliases,confidence FROM entities WHERE name=? AND entity_type=?",
            (duplicate_name, entity_type),
        ).fetchone()
        if not dup:
            return False

        aliases = {
            x.strip() for x in ((keep[0] if keep else "") or "").split(",") if x.strip()
        }
        aliases.update(x.strip() for x in (dup[0] or "").split(",") if x.strip())
        aliases.discard(canonical_name)
        aliases.add(duplicate_name)
        confidence = max(
            float(keep[1]) if keep else 0.0,
            float(dup[1]),
        )
        db.execute(
            """INSERT INTO entities(name,entity_type,aliases,confidence)
               VALUES(?,?,?,?)
               ON CONFLICT(name,entity_type) DO UPDATE SET
               aliases=excluded.aliases,confidence=excluded.confidence""",
            (
                canonical_name,
                entity_type,
                ",".join(sorted(aliases, key=lambda x: (x.casefold(), x))),
                confidence,
            ),
        )

        # Rewire document links collision-safely and preserve the stronger confidence.
        doc_links = db.execute(
            "SELECT document_id,confidence FROM document_entities "
            "WHERE entity_name=? AND entity_type=?",
            (duplicate_name, entity_type),
        ).fetchall()
        for document_id, link_confidence in doc_links:
            existing = db.execute(
                "SELECT confidence FROM document_entities "
                "WHERE document_id=? AND entity_name=? AND entity_type=?",
                (document_id, canonical_name, entity_type),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE document_entities SET confidence=MAX(confidence,?) "
                    "WHERE document_id=? AND entity_name=? AND entity_type=?",
                    (link_confidence, document_id, canonical_name, entity_type),
                )
            else:
                db.execute(
                    "INSERT INTO document_entities(document_id,entity_name,entity_type,confidence) "
                    "VALUES(?,?,?,?)",
                    (document_id, canonical_name, entity_type, link_confidence),
                )
        db.execute(
            "DELETE FROM document_entities WHERE entity_name=? AND entity_type=?",
            (duplicate_name, entity_type),
        )

        rels = db.execute(
            "SELECT source_name,relation,target_name,confidence FROM relations "
            "WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        ).fetchall()
        db.execute(
            "DELETE FROM relations WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        )
        for source, relation, target, rel_confidence in rels:
            source = canonical_name if source == duplicate_name else source
            target = canonical_name if target == duplicate_name else target
            existing = db.execute(
                "SELECT confidence FROM relations "
                "WHERE source_name=? AND relation=? AND target_name=?",
                (source, relation, target),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE relations SET confidence=MAX(confidence,?) "
                    "WHERE source_name=? AND relation=? AND target_name=?",
                    (rel_confidence, source, relation, target),
                )
            else:
                db.execute(
                    "INSERT INTO relations VALUES(?,?,?,?)",
                    (source, relation, target, rel_confidence),
                )

        doc_rels = db.execute(
            "SELECT document_id,source_name,relation,target_name,confidence "
            "FROM document_relations WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        ).fetchall()
        db.execute(
            "DELETE FROM document_relations WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        )
        for document_id, source, relation, target, rel_confidence in doc_rels:
            source = canonical_name if source == duplicate_name else source
            target = canonical_name if target == duplicate_name else target
            existing = db.execute(
                "SELECT confidence FROM document_relations "
                "WHERE document_id=? AND source_name=? AND relation=? AND target_name=?",
                (document_id, source, relation, target),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE document_relations SET confidence=MAX(confidence,?) "
                    "WHERE document_id=? AND source_name=? AND relation=? AND target_name=?",
                    (rel_confidence, document_id, source, relation, target),
                )
            else:
                db.execute(
                    "INSERT INTO document_relations VALUES(?,?,?,?,?)",
                    (document_id, source, relation, target, rel_confidence),
                )

        evidence_rows = db.execute(
            "SELECT document_id,source_name,relation,target_name,evidence_document_id,status,checked_at "
            "FROM relation_evidence WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        ).fetchall()
        db.execute(
            "DELETE FROM relation_evidence WHERE source_name=? OR target_name=?",
            (duplicate_name, duplicate_name),
        )
        for document_id, source, relation, target, evidence_document_id, ev_status, checked_at in evidence_rows:
            source = canonical_name if source == duplicate_name else source
            target = canonical_name if target == duplicate_name else target
            db.execute(
                "INSERT OR REPLACE INTO relation_evidence("
                "document_id,source_name,relation,target_name,evidence_document_id,status,checked_at"
                ") VALUES(?,?,?,?,?,?,?)",
                (document_id, source, relation, target, evidence_document_id, ev_status, checked_at),
            )

        db.execute(
            "INSERT OR IGNORE INTO entity_sources(entity_name,entity_type,source,document_id) "
            "SELECT ?,entity_type,source,document_id FROM entity_sources "
            "WHERE entity_name=? AND entity_type=?",
            (canonical_name, duplicate_name, entity_type),
        )
        db.execute(
            "DELETE FROM entity_sources WHERE entity_name=? AND entity_type=?",
            (duplicate_name, entity_type),
        )
        db.execute(
            "DELETE FROM entity_aliases WHERE canonical_name=? AND entity_type=?",
            (duplicate_name, entity_type),
        )
        for alias in aliases:
            db.execute(
                "INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) "
                "VALUES(?,?,?)",
                (alias.casefold(), canonical_name, entity_type),
            )
        db.execute(
            "INSERT INTO entity_merge_log(canonical_name,duplicate_name,entity_type,reason) "
            "VALUES(?,?,?,?)",
            (canonical_name, duplicate_name, entity_type, reason),
        )
        db.execute(
            "DELETE FROM entities WHERE name=? AND entity_type=?",
            (duplicate_name, entity_type),
        )
        return True
