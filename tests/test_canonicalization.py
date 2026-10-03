from pathlib import Path
from nayvadius.models import Document, Entity, ProcessedDocument, Relation
from nayvadius.store import upsert_document, save_result
from nayvadius.db import connect

def test_aliases_canonicalize_same_entity(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple Inc."), "a",
        [Entity("Apple Inc.", "Companies", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    second = ProcessedDocument(Document("2", "B", "Apple"), "b",
        [Entity("Apple", "Companies", 0.9, ("Apple Inc.",))], ["source/test"],
        relations=[Relation("Apple", "related_to", "Apple")])
    upsert_document(second.document); save_result(second)
    with connect() as db:
        entities = db.execute("SELECT name,entity_type FROM entities ORDER BY name").fetchall()
        aliases = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY alias").fetchall()
        relation = db.execute("SELECT source_name,target_name FROM relations").fetchone()
    assert entities == [("Apple Inc.", "Companies")]
    assert ("apple", "Apple Inc.", "Companies") in aliases
    assert ("apple inc.", "Apple Inc.", "Companies") in aliases
    assert relation == ("Apple Inc.", "Apple Inc.")

