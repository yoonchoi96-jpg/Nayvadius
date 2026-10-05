from pathlib import Path

from nayvadius.db import connect
from nayvadius.models import Document, Entity, ProcessedDocument
from nayvadius.store import save_result, upsert_document


def test_reprocessing_removes_stale_entity_provenance(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.db.settings.state_path", db_path)

    doc = Document("d1", "Doc", "content", source="abraham")
    first = ProcessedDocument(doc, "summary", [Entity("Old Person", "People", 0.9)], ["tag"])
    upsert_document(doc, force=True)
    save_result(first)

    updated = Document("d1", "Doc", "content", source="abraham")
    second = ProcessedDocument(updated, "summary", [Entity("New Person", "People", 0.9)], ["tag"])
    upsert_document(updated, force=True)
    save_result(second)

    with connect(db_path) as db:
        assert db.execute("SELECT content FROM documents WHERE id='d1'").fetchone() == ("content",)
        assert db.execute("SELECT entity_name FROM entity_sources ORDER BY entity_name").fetchall() == [("New Person",)]
        assert db.execute("SELECT entity_name FROM document_entities ORDER BY entity_name").fetchall() == [("New Person",)]
