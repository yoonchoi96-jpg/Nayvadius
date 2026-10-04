import sqlite3
from pathlib import Path

from nayvadius.db import connect
from nayvadius.store import save_result
from nayvadius.models import Document, Entity, ProcessedDocument, Relation
from nayvadius.writer import write_entities_from_db


def _result(doc_id, source, entity_name, entity_type="People"):
    return ProcessedDocument(
        Document(doc_id, doc_id, "content", source),
        "summary",
        [Entity(entity_name, entity_type, 0.95)],
        [f"source/{source}"],
    )


def test_same_canonical_entity_keeps_both_source_provenance(tmp_path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))

    save_result(_result("doc-a", "abraham", "Taylor Swift"))
    save_result(_result("doc-b", "jacques", "Taylor Swift"))

    with connect() as db:
        entity = db.execute(
            "SELECT name,entity_type FROM entities WHERE name='Taylor Swift'"
        ).fetchall()
        sources = db.execute(
            """SELECT source,document_id FROM entity_sources
               WHERE entity_name='Taylor Swift' AND entity_type='People'
               ORDER BY source,document_id"""
        ).fetchall()

    assert entity == [("Taylor Swift", "People")]
    assert sources == [("abraham", "doc-a"), ("jacques", "doc-b")]


def test_same_alias_across_entity_types_stays_separate(tmp_path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))

    save_result(_result("doc-company", "abraham", "Apple", "Organizations"))
    save_result(_result("doc-product", "jacques", "Apple", "Products"))

    with connect() as db:
        rows = db.execute(
            "SELECT name,entity_type FROM entities WHERE name='Apple' ORDER BY entity_type"
        ).fetchall()

    assert rows == [("Apple", "Organizations"), ("Apple", "Products")]


def test_entity_writer_contains_documents_and_relations(tmp_path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))
    save_result(_result("doc-a", "abraham", "Taylor Swift"))
    save_result(ProcessedDocument(
        Document("doc-b", "Second", "content", "jacques"),
        "summary",
        [Entity("Taylor Swift", "People", 0.95)],
        ["source/jacques"],
        relations=[Relation("Taylor Swift", "performed", "Example Song", 0.9)],
    ))
    with connect() as db:
        write_entities_from_db(db, tmp_path / "output")
    note = (tmp_path / "output" / "entities" / "People" / "Taylor Swift.md").read_text()
    assert "## Sources" in note
    assert "[[doc-a]]" in note
    assert "[[doc-b]]" in note
    assert "## Relations" in note
    assert "performed" in note
