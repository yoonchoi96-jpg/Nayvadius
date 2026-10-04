from .db import connect, save_vocabulary, save_vocabulary_alias, save_vocabulary_source, resolve_vocabulary_id, link_document_vocabularies, merge_vocabulary
from .models import Vocabulary
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


def link_vocabulary(vocabulary, explicit_entities=()):
    with connect() as db:
        alias_candidates = [_norm_alias(vocabulary.id), _norm_alias(vocabulary.word), _norm_alias(vocabulary.traditional)]
        canonical_id = next((db.execute("SELECT canonical_id FROM vocabulary_aliases WHERE alias=?", (a,)).fetchone()[0]
                             for a in alias_candidates if a and db.execute("SELECT canonical_id FROM vocabulary_aliases WHERE alias=?", (a,)).fetchone()), vocabulary.id)
        existing = db.execute("SELECT word,traditional,pinyin,pos,meaning_ko,hsk_levels,wordbooks,source,metadata FROM vocabularies WHERE id=?", (canonical_id,)).fetchone()
        if existing and canonical_id != vocabulary.id:
            old_levels=set(filter(None,(existing[5] or "").split("|"))); old_levels.update(vocabulary.hsk_levels)
            old_books=set(filter(None,(existing[6] or "").split("|"))); old_books.update(vocabulary.wordbooks)
            old_meta=json.loads(existing[8] or "{}"); new_meta=dict(old_meta); new_meta.update(vocabulary.metadata)
            from .models import Vocabulary as V
            vocabulary=V(canonical_id, existing[0] or vocabulary.word, existing[1] or vocabulary.traditional,
                         vocabulary.pinyin or existing[2] or "", vocabulary.pos or existing[3] or "",
                         vocabulary.meaning_ko or existing[4] or "", tuple(sorted(old_levels)),
                         tuple(sorted(old_books)), existing[7] or vocabulary.source, new_meta)
        explicit = {_norm_alias(x) for x in explicit_entities if _norm_alias(x)}
        forms = {_norm_alias(vocabulary.word), _norm_alias(vocabulary.traditional)} - {""}
        links=[]; seen=set()
        for value in explicit:
            for name, entity_type in db.execute("SELECT canonical_name,entity_type FROM entity_aliases WHERE alias=?", (value,)):
                key=(name,entity_type)
                if key not in seen: links.append((name,entity_type,"explicit",1.0)); seen.add(key)
        for form in forms:
            for name, entity_type in db.execute("SELECT name,entity_type FROM entities WHERE lower(name)=?", (form,)):
                key=(name,entity_type)
                if key not in seen: links.append((name,entity_type,"exact",1.0)); seen.add(key)
        save_vocabulary(vocabulary, links)
        # Merge existing records that share the same normalized headword.
        with connect() as db:
            rows = []
            for value in (vocabulary.word, vocabulary.traditional):
                alias = _norm_alias(value)
                if alias:
                    rows.extend(db.execute("SELECT canonical_id FROM vocabulary_aliases WHERE alias=?", (alias,)).fetchall())
        for (other_id,) in dict.fromkeys(rows):
            if other_id != vocabulary.id:
                merge_vocabulary(vocabulary.id, other_id)
        for alias in [vocabulary.id, vocabulary.word, vocabulary.traditional]:
            save_vocabulary_alias(alias, vocabulary.id)
        save_vocabulary_source(vocabulary.id, vocabulary.id, vocabulary.source, vocabulary.metadata)
        return links

def link_document_to_vocabularies(document_id, content, explicit_ids=(), vocabulary_index=None):
    text = _norm_alias(content)
    with connect() as db:
        explicit = []
        for value in explicit_ids:
            canonical = resolve_vocabulary_id(value)
            if canonical:
                explicit.append(canonical)
        rows = vocabulary_index if vocabulary_index is not None else db.execute("SELECT id,word,traditional FROM vocabularies").fetchall()
        candidates = []
        for vid, word, traditional in rows:
            forms = {x for x in (_norm_alias(word), _norm_alias(traditional)) if x}
            if any(form in text for form in forms):
                candidates.append((vid, "exact", 1.0))
        db.execute("DELETE FROM document_vocabulary_links WHERE document_id=?", (document_id,))
        for vid in dict.fromkeys(explicit):
            db.execute("INSERT OR REPLACE INTO document_vocabulary_links VALUES(?,?,?,?)",
                       (document_id, vid, "explicit", 1.0))
        for vid, match_type, confidence in candidates:
            if vid not in explicit:
                db.execute("INSERT OR REPLACE INTO document_vocabulary_links VALUES(?,?,?,?)",
                           (document_id, vid, match_type, confidence))
        return len(set(explicit) | {x[0] for x in candidates})

def reconcile_document_vocabularies(documents):
    with connect() as db:
        vocabulary_index = db.execute("SELECT id,word,traditional FROM vocabularies").fetchall()
    total = 0
    for document_id, content, explicit_ids in documents:
        total += link_document_to_vocabularies(document_id, content, explicit_ids, vocabulary_index)
    return total

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
            vocab_rows = db.execute(
                "SELECT id,word,traditional FROM vocabularies WHERE word=? OR traditional=?",
                (name, name),
            ).fetchall()
            for vocabulary_id, word, traditional in vocab_rows:
                db.execute(
                    "INSERT OR REPLACE INTO entity_vocabulary_links VALUES(?,?,?,?,?)",
                    (name, e.entity_type, vocabulary_id, "exact", 1.0),
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
