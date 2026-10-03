from .db import connect
from .hash import content_hash
import json

def upsert_document(doc):
    h = content_hash(doc.content)
    with connect() as db:
        old = db.execute("SELECT content_hash FROM documents WHERE id=?", (doc.id,)).fetchone()
        if old and old[0] == h:
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
    payload = json.dumps({
        "summary": result.summary,
        "entities": [e.__dict__ for e in result.entities],
        "tags": result.tags,
        "related_ids": result.related_ids,
        "importance": result.importance,
        "document_type": result.document_type,
        "translation_ko": result.translation_ko,
        "relations": [r.__dict__ for r in result.relations],
    }, ensure_ascii=False)

    with connect() as db:
        db.execute("DELETE FROM document_entities WHERE document_id=?", (result.document.id,))
        db.execute("DELETE FROM document_relations WHERE document_id=?", (result.document.id,))

        for x in result.relations:
            db.execute(
                "INSERT OR REPLACE INTO relations VALUES(?,?,?,?)",
                (x.source, x.relation, x.target, x.confidence),
            )
            db.execute(
                "INSERT OR REPLACE INTO document_relations VALUES(?,?,?,?,?)",
                (result.document.id, x.source, x.relation, x.target, x.confidence),
            )

        db.execute("INSERT OR REPLACE INTO results VALUES(?,?)", (result.document.id, payload))

        for e in result.entities:
            db.execute(
                "INSERT OR REPLACE INTO entities VALUES(?,?,?,?)",
                (e.name, e.entity_type, ",".join(e.aliases), e.confidence),
            )
            db.execute(
                "INSERT OR REPLACE INTO document_entities VALUES(?,?,?,?)",
                (result.document.id, e.name, e.entity_type, e.confidence),
            )

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
