from .db import connect, save_vocabulary, save_vocabulary_alias, save_vocabulary_source, resolve_vocabulary_id, link_document_vocabularies, merge_vocabulary, save_document_source
from .models import Vocabulary
from .hash import content_hash
from .vocabulary_matcher import VocabularyMatcher
import json
import re
import hashlib
import unicodedata

def _norm_alias(value):
    value = str(value or "").strip().casefold()
    return re.sub(r"[\s\u3000]+", " ", value)


def _norm_entity_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(
        "".join(char if char.isalnum() else " " for char in value).split()
    )


def _canonical_entity(db, entity):
    """Resolve to an existing canonical name within the same entity_type.

    Unique match -> canonical name; ambiguous or no match -> incoming name.
    """
    if db.execute(
        "SELECT 1 FROM entities WHERE name=? AND entity_type=?",
        (entity.name, entity.entity_type),
    ).fetchone():
        return entity.name

    values = [entity.name, *entity.aliases]
    exact_aliases = set()
    for value in values:
        alias = _norm_alias(value)
        if alias:
            exact_aliases.update(
                row[0] for row in db.execute(
                    "SELECT canonical_name FROM entity_aliases "
                    "WHERE alias=? AND entity_type=?",
                    (alias, entity.entity_type),
                )
            )
    if len(exact_aliases) == 1:
        return next(iter(exact_aliases))
    if len(exact_aliases) > 1:
        return entity.name

    normalized_values = {_norm_entity_name(value) for value in values}
    normalized_values.discard("")
    exact_names = {
        name for (name,) in db.execute(
            "SELECT name FROM entities WHERE entity_type=?",
            (entity.entity_type,),
        )
        if _norm_entity_name(name) in normalized_values
    }
    if len(exact_names) == 1:
        return next(iter(exact_names))
    if len(exact_names) > 1:
        return entity.name

    normalized_aliases = {
        canonical_name
        for alias, canonical_name in db.execute(
            "SELECT alias,canonical_name FROM entity_aliases WHERE entity_type=?",
            (entity.entity_type,),
        )
        if _norm_entity_name(alias) in normalized_values
    }
    if len(normalized_aliases) == 1:
        return next(iter(normalized_aliases))
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
    if len(unique) == 1:
        return unique[0][0]
    if not unique:
        names = list(dict.fromkeys(
            r for r in db.execute("SELECT name,entity_type FROM entities").fetchall()
            if _norm_alias(r[0]) == alias
        ))
        if len(names) == 1:
            return names[0][0]
    return value

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
    source_id = vocabulary.id
    source_name = vocabulary.source
    source_metadata = dict(vocabulary.metadata)
    alias_candidates = [_norm_alias(vocabulary.id), _norm_alias(vocabulary.word), _norm_alias(vocabulary.traditional)]
    with connect() as db:
        canonical_id = vocabulary.id
        for alias in alias_candidates:
            if not alias:
                continue
            row = db.execute("SELECT canonical_id FROM vocabulary_aliases WHERE alias=?", (alias,)).fetchone()
            if row:
                canonical_id = row[0]
                break
        existing = db.execute("SELECT word,traditional,pinyin,pos,meaning_ko,hsk_levels,wordbooks,source,metadata FROM vocabularies WHERE id=?", (canonical_id,)).fetchone()
        if existing and canonical_id != vocabulary.id:
            levels = set(filter(None, (existing[5] or "").split("|"))) | set(vocabulary.hsk_levels)
            books = set(filter(None, (existing[6] or "").split("|"))) | set(vocabulary.wordbooks)
            meta = json.loads(existing[8] or "{}")
            meta.update(vocabulary.metadata)
            from .models import Vocabulary as V
            vocabulary = V(canonical_id, existing[0] or vocabulary.word, existing[1] or vocabulary.traditional,
                           vocabulary.pinyin or existing[2] or "", vocabulary.pos or existing[3] or "",
                           vocabulary.meaning_ko or existing[4] or "", tuple(sorted(levels)),
                           tuple(sorted(books)), existing[7] or vocabulary.source, meta)
        explicit = {_norm_alias(x) for x in explicit_entities if _norm_alias(x)}
        forms = {_norm_alias(vocabulary.word), _norm_alias(vocabulary.traditional)} - {""}
        links=[]; seen=set()
        for value in explicit:
            for name, entity_type in db.execute("SELECT canonical_name,entity_type FROM entity_aliases WHERE alias=?", (value,)):
                key=(name,entity_type)
                if key not in seen:
                    links.append((name,entity_type,"explicit",1.0)); seen.add(key)
        for form in forms:
            for name, entity_type in db.execute("SELECT name,entity_type FROM entities WHERE lower(name)=?", (form,)):
                key=(name,entity_type)
                if key not in seen:
                    links.append((name,entity_type,"exact",1.0)); seen.add(key)
    save_vocabulary(vocabulary, links)
    for alias in [source_id, vocabulary.word, vocabulary.traditional]:
        save_vocabulary_alias(alias, vocabulary.id)
    save_vocabulary_source(vocabulary.id, source_id, source_name, source_metadata)
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

def reconcile_all_vocabularies():
    with connect() as db:
        vocabularies = db.execute("SELECT id,word,traditional FROM vocabularies").fetchall()
        documents = db.execute("SELECT id,content FROM documents").fetchall()
    return reconcile_document_vocabularies([(doc_id, content, ()) for doc_id, content in documents]) if vocabularies else 0

def reconcile_document_vocabularies(documents):
    with connect() as db:
        vocabulary_index = db.execute("SELECT id,word,traditional FROM vocabularies").fetchall()
    matcher = VocabularyMatcher(vocabulary_index)
    total = 0
    for document_id, content, explicit_ids in documents:
        if not content:
            continue
        matches = matcher.match(content)
        with connect() as db:
            explicit = []
            for value in explicit_ids:
                canonical = resolve_vocabulary_id(value)
                if canonical:
                    explicit.append(canonical)
            db.execute("DELETE FROM document_vocabulary_links WHERE document_id=?", (document_id,))
            for vid in dict.fromkeys(explicit):
                db.execute(
                    "INSERT OR REPLACE INTO document_vocabulary_links VALUES(?,?,?,?)",
                    (document_id, vid, "explicit", 1.0),
                )
            for vid, count in matches.items():
                if vid not in explicit:
                    confidence = min(1.0, 0.8 + min(count, 4) * 0.05)
                    db.execute(
                        "INSERT OR REPLACE INTO document_vocabulary_links VALUES(?,?,?,?)",
                        (document_id, vid, "exact", confidence),
                    )
            total += len(set(explicit) | set(matches))
    return total

def upsert_document(doc, force=False):
    h = content_hash(doc.content)
    with connect() as db:
        old = db.execute("SELECT content_hash FROM documents WHERE id=?", (doc.id,)).fetchone()
        if old and old[0] == h and not force:
            return False
        metadata = dict(doc.metadata or {})
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        db.execute(
            """INSERT INTO documents(id,title,content_hash,source,status,content,metadata)
               VALUES(?,?,?,?,'pending',?,?)
               ON CONFLICT(id) DO UPDATE SET
               title=excluded.title, content_hash=excluded.content_hash,
               source=excluded.source, status='pending', content=excluded.content,
               metadata=excluded.metadata, updated_at=CURRENT_TIMESTAMP""",
            (doc.id, doc.title, h, doc.source, doc.content, metadata_json),
        )
    source_id = metadata.get("source_id") or metadata.get("external_id")
    if source_id:
        save_document_source(doc.id, doc.source, source_id, metadata)
    return True

def save_result(result):
    payload = _result_payload(result)

    with connect() as db:
        # Remove this document's old entity provenance before replacing its
        # extracted entities. Otherwise reprocessing can leave ghost source
        # bridges for entities no longer present in the document.
        old_entities = db.execute(
            "SELECT entity_name,entity_type FROM document_entities WHERE document_id=?",
            (result.document.id,),
        ).fetchall()
        old_sources = db.execute(
            "SELECT entity_name,entity_type,source,document_id FROM entity_sources WHERE document_id=?",
            (result.document.id,),
        ).fetchall()
        db.execute("DELETE FROM document_entities WHERE document_id=?", (result.document.id,))
        db.execute("DELETE FROM document_relations WHERE document_id=?", (result.document.id,))
        # Delete provenance by the document itself, not the incoming source.
        # A reprocessed document may legitimately change source metadata; old
        # source rows must not survive and create false cross-source bridges.
        for entity_name, entity_type, source, document_id in old_sources:
            db.execute(
                "DELETE FROM entity_sources WHERE entity_name=? AND entity_type=? AND source=? AND document_id=?",
                (entity_name, entity_type, source, document_id),
            )

        canonical = {}
        for e in result.entities:
            name = _canonical_entity(db, e)
            canonical[e.name] = name
            canonical.setdefault(_norm_alias(e.name), name)
            extra = (e.name,) if _norm_alias(e.name) != _norm_alias(name) else ()
            all_aliases = [*e.aliases, *extra]
            aliases = _merge_aliases(db, name, e.entity_type, all_aliases)
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
            for alias in all_aliases:
                if _norm_alias(alias):
                    db.execute(
                        "INSERT OR IGNORE INTO entity_aliases(alias,canonical_name,entity_type) VALUES(?,?,?)",
                        (_norm_alias(alias), name, e.entity_type),
                    )
            db.execute(
                "INSERT OR REPLACE INTO document_entities VALUES(?,?,?,?)",
                (result.document.id, name, e.entity_type, e.confidence),
            )
            db.execute(
                "INSERT OR REPLACE INTO entity_sources(entity_name,entity_type,source,document_id) VALUES(?,?,?,?)",
                (name, e.entity_type, result.document.source, result.document.id),
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
            source = canonical.get(x.source) or canonical.get(_norm_alias(x.source)) or _resolve_relation_endpoint(db, x.source)
            target = canonical.get(x.target) or canonical.get(_norm_alias(x.target)) or _resolve_relation_endpoint(db, x.target)
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
