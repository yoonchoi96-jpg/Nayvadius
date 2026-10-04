from .db import connect, save_vocabulary
from .hash import content_hash
import json
import re
import hashlib

def _norm_alias(value):
    value = str(value or "").strip().casefold()
    return re.sub(r"[\s\u3000]+", " ", value)

def _canonical_entity(db, entity):
    matches = []
    for value in [entity.name, *entity.aliases]:
        alias = _norm_alias(value)
        if alias:
            matches.extend(db.execute(
                "SELECT canonical_name,entity_type FROM entity_aliases WHERE alias=?",
                (alias,),
            ).fetchall())
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1 and unique[0][1] == entity.entity_type:
        return unique[0][0]
    return entity.name

def _merge_aliases(db, canonical_name, entity_type, aliases):
    row = db.execute(
        "SELECT aliases FROM entities WHERE name=? AND entity_type=?",
        (canonical_name, entity_type),
    ).fetchone()
    values = set(x.strip() for x in ((row[0] if row else "") or "").split(",") if x.strip())
    values.update(x.strip() for x in aliases if _norm_alias(x))
    values.discard(canonical_name)
    return ",".join(sorted(values, key=lambda x: (_norm_alias(x), x)))

def _resolve_relation_endpoint(db, value):
    alias = _norm_alias(value)
    if not alias:
        return value
    rows = db.execute(
        "SELECT canonical_name,entity_type FROM entity_aliases WHERE alias=?",
        (alias,),
    ).fetchall()
    unique = list(dict.fromkeys(rows))
    return unique[0][0] if len(unique) == 1 else value

def _result_payload(result):
    return json.dumps({
        "summary": result.summary,
        "entities": [e.__dict__ for e in result.entities],
        "tags": result.tags,
        "related_ids": result.related_ids,
        "importance": result.importance,
        "document_type": result.document_type,
        "translation_ko": result.translation_ko,
        "relations": [r.__dict__ for r in result.relations],
    }, ensure_ascii=False, sort_keys=True)

def result_hash(result):
    return hashlib.sha256(_result_payload(result).encode("utf-8")).hexdigest()

def result_is_current(result):
    with connect() as db:
        row = db.execute("SELECT payload FROM results WHERE document_id=?", (result.document.id,)).fetchone()
    if not row:
        return False
    return hashlib.sha256(row[0].encode("utf-8")).hexdigest() == result_hash(result)

def upsert_document(doc, force=False):
    h = content_hash(doc.content)
    with connect() as db:
        old = db.execute("SELECT content_hash FROM documents WHERE id=?", (doc.id,)).fetchone()
        if old and old[0] == h and not force:
            return False
        db.execute(
            """INSERT INTO documents(id,title,content_hash,source,status)
               VALUES(?,?,?,?,'pending')
               ON CONFLICT(id) DO UPDATE SET
               title=excluded.title, content_hash=excluded.content_hash,
               source=excluded.source, status='pending',
               updated_at=CURRENT_TIMESTAMP""",
            (doc.id, doc.title, h, doc.source),
        )
    return True

def save_result(result):
    payload = _result_payload(result)

    with connect() as db:
        db.execute("DELETE FROM document_entities WHERE document_id=?", (result.document.id,))
        db.execute("DELETE FROM document_relations WHERE document_id=?", (result.document.id,))

        canonical = {}
        for e in result.entities:
            name = _canonical_entity(db, e)
            canonical[e.name] = name
            aliases = _merge_aliases(db, name, e.entity_type, e.aliases)
            db.execute(
                """INSERT INTO entities(name,entity_type,aliases,confidence) VALUES(?,?,?,?)
                   ON CONFLICT(name,entity_type) DO UPDATE SET
                   aliases=excluded.aliases,
                   confidence=MAX(entities.confidence, excluded.confidence)""",
                (name, e.entity_type, aliases, e.confidence),
            )
            db.execute(
                "INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",
                (_norm_alias(name), name, e.entity_type),
            )
            for alias in e.aliases:
                if _norm_alias(alias):
                    db.execute(
                        "INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",
                        (_norm_alias(alias), name, e.entity_type),
                    )
            db.execute(
                "INSERT OR REPLACE INTO document_entities VALUES(?,?,?,?)",
                (result.document.id, name, e.entity_type, e.confidence),
            )

        for x in result.relations:
            source = canonical.get(x.source) or _resolve_relation_endpoint(db, x.source)
            target = canonical.get(x.target) or _resolve_relation_endpoint(db, x.target)
            db.execute(
                "INSERT OR REPLACE INTO relations VALUES(?,?,?,?)",
                (source, x.relation, target, x.confidence),
            )
            db.execute(
                "INSERT OR REPLACE INTO document_relations VALUES(?,?,?,?,?)",
                (result.document.id, source, x.relation, target, x.confidence),
            )

        db.execute("INSERT OR REPLACE INTO results VALUES(?,?)", (result.document.id, payload))

        db.execute(
            """DELETE FROM relations
               WHERE NOT EXISTS (
                 SELECT 1 FROM document_relations dr
                 WHERE dr.source_name=relations.source_name
                   AND dr.relation=relations.relation
                   AND dr.target_name=relations.target_name
               )"""
        )
        db.execute("UPDATE documents SET status='done' WHERE id=?", (result.document.id,))
