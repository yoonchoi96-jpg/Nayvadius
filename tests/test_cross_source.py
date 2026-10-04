from pathlib import Path

from nayvadius.db import connect
from nayvadius.models import Document, Entity, ProcessedDocument, Relation
from nayvadius.store import save_result


def _result(doc_id, source, entity_name):
    doc = Document(doc_id, doc_id, "content", source)
    return ProcessedDocument(
        doc,
        "summary",
        [Entity(entity_name, "People", 0.9)],
        [f"source/{source}"],
        relations=[],
        importance=0.5,
        document_type="note",
    )


def test_same_canonical_entity_is_shared_across_sources(tmp_path: Path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))

    save_result(_result("abraham-1", "abraham", "Taylor Swift"))
    save_result(_result("jacques-1", "jacques", "Taylor Swift"))

    with connect() as db:
        entities = db.execute(
            "SELECT name,entity_type FROM entities WHERE name='Taylor Swift'"
        ).fetchall()
        docs = db.execute(
            "SELECT document_id,entity_name,entity_type FROM document_entities "
            "WHERE entity_name='Taylor Swift' ORDER BY document_id"
        ).fetchall()
        sources = db.execute(
            "SELECT source,document_id FROM entity_sources "
            "WHERE entity_name='Taylor Swift' ORDER BY source"
        ).fetchall()

    assert entities == [("Taylor Swift", "People")]
    assert docs == [
        ("abraham-1", "Taylor Swift", "People"),
        ("jacques-1", "Taylor Swift", "People"),
    ]
    assert sources == [
        ("abraham", "abraham-1"),
        ("jacques", "jacques-1"),
    ]


def test_same_alias_does_not_cross_entity_types(tmp_path: Path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))

    first = ProcessedDocument(
        Document("company-1", "Company", "content", "abraham"),
        "summary",
        [Entity("Apple", "Companies", 0.9, ("Apple Inc.",))],
        ["source/abraham"],
    )
    second = ProcessedDocument(
        Document("brand-1", "Brand", "content", "jacques"),
        "summary",
        [Entity("Apple", "Brands", 0.9)],
        ["source/jacques"],
    )
    save_result(first)
    save_result(second)

    with connect() as db:
        rows = db.execute(
            "SELECT name,entity_type FROM entities WHERE name='Apple' ORDER BY entity_type"
        ).fetchall()

    assert rows == [("Apple", "Brands"), ("Apple", "Companies")]
