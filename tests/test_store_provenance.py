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


def test_document_metadata_and_source_provenance(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.db.settings.state_path", db_path)

    doc = Document(
        "d2", "External article", "body", source="readwise",
        metadata={
            "source_id": "reader-123",
            "url": "https://example.test/article",
            "plugin_version": "1.2.3",
            "extra": {"author": "A"},
        },
    )
    assert upsert_document(doc, force=True) is True

    with connect(db_path) as db:
        metadata = db.execute(
            "SELECT metadata FROM documents WHERE id='d2'"
        ).fetchone()[0]
        source = db.execute(
            "SELECT source,source_id,document_id,metadata FROM document_sources"
        ).fetchone()

    import json
    assert json.loads(metadata)["plugin_version"] == "1.2.3"
    assert source[0:3] == ("readwise", "reader-123", "d2")
    assert json.loads(source[3])["url"] == "https://example.test/article"


def test_source_priority_and_conflict_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.db.settings.state_path", db_path)

    from nayvadius.db import compare_source_priority, record_source_conflict, source_priority

    assert source_priority("abraham") > source_priority("abel")
    assert compare_source_priority("abraham", "abel") == 1
    assert compare_source_priority("unknown", "abraham") == -1

    record_source_conflict(
        "d2", "title", "abraham", "abel",
        "Authoritative title", "Other title", "review",
    )

    with connect(db_path) as db:
        row = db.execute(
            "SELECT document_id,field,existing_source,incoming_source,resolution "
            "FROM source_conflicts"
        ).fetchone()
    assert row == ("d2", "title", "abraham", "abel", "review")


def test_source_identity_collision_is_recorded_and_original_mapping_is_preserved(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.db.settings.state_path", db_path)

    from nayvadius.db import save_document_source

    assert save_document_source("doc-1", "abraham", "external-1", {"version": 1}) is True
    assert save_document_source("doc-1", "abraham", "external-1", {"version": 2}) is True
    assert save_document_source("doc-2", "abraham", "external-1", {"version": 3}) is False

    with connect(db_path) as db:
        source_row = db.execute(
            "SELECT source_id,document_id,metadata FROM document_sources"
        ).fetchone()
        conflict = db.execute(
            "SELECT document_id,field,existing_value,incoming_value,resolution "
            "FROM source_conflicts"
        ).fetchone()

    assert source_row[0:2] == ("external-1", "doc-1")
    assert '"version": 2' in source_row[2]
    assert conflict == (
        "doc-2", "source_identity", "doc-1", "doc-2", "review"
    )
