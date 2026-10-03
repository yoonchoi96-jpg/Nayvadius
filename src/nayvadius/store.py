import json
from .db import connect
from .hash import content_hash
from .models import Document, ProcessedDocument

def upsert_document(doc: Document) -> bool:
    h = content_hash(doc.content)
    with connect() as db:
        old = db.execute("SELECT content_hash FROM documents WHERE id=?", (doc.id,)).fetchone()
        if old and old[0] == h:
            return False
        db.execute("""INSERT INTO documents(id,title,content_hash,source,status)
                      VALUES(?,?,?,?, 'pending')
                      ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                      content_hash=excluded.content_hash, source=excluded.source,
                      status='pending', updated_at=CURRENT_TIMESTAMP""",
                   (doc.id, doc.title, h, doc.source))
    return True

def save_result(result: ProcessedDocument) -> None:
    payload = json.dumps({
        "summary": result.summary,
        "entities": [e.__dict__ for e in result.entities],
        "tags": result.tags,
        "related_ids": result.related_ids
    }, ensure_ascii=False)
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO results(document_id,payload) VALUES(?,?)", (result.document.id,payload))
        db.execute("UPDATE documents SET status='done' WHERE id=?", (result.document.id,))
        for e in result.entities:
            db.execute("INSERT OR REPLACE INTO entities VALUES(?,?,?)", (e.name,e.entity_type,e.confidence))
            db.execute("INSERT OR IGNORE INTO document_entities VALUES(?,?,?)", (result.document.id,e.name,e.entity_type))
