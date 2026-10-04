from pathlib import Path
from nayvadius.models import Document, Entity, ProcessedDocument, Relation
from nayvadius.store import upsert_document, save_result
from nayvadius.db import connect

def test_aliases_canonicalize_same_entity(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple Inc."), "a", [Entity("Apple Inc.", "Companies", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    second = ProcessedDocument(Document("2", "B", "Apple"), "b", [Entity("Apple", "Companies", 0.9, ("Apple Inc.",))], ["source/test"], relations=[Relation("Apple", "related_to", "Apple")])
    upsert_document(second.document); save_result(second)
    with connect() as db:
        entities = db.execute("SELECT name,entity_type FROM entities ORDER BY name").fetchall()
        aliases = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY alias").fetchall()
        relation = db.execute("SELECT source_name,target_name FROM relations").fetchone()
    assert entities == [("Apple Inc.", "Companies")]
    assert ("apple", "Apple Inc.", "Companies") in aliases
    assert ("apple inc.", "Apple Inc.", "Companies") in aliases
    assert relation == ("Apple Inc.", "Apple Inc.")

def test_conflicting_alias_does_not_overwrite_existing_mapping(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple"), "a", [Entity("Apple Inc.", "Companies", 0.9, ("Apple",))], ["source/test"])
    second = ProcessedDocument(Document("2", "B", "Apple"), "b", [Entity("Apple Music", "Companies", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    upsert_document(second.document); save_result(second)
    with connect() as db:
        rows = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases WHERE alias='apple'").fetchall()
    assert rows == [("apple", "Apple Inc.", "Companies")]

def test_relation_resolves_historical_alias(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple Inc."), "a", [Entity("Apple Inc.", "Companies", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    second = ProcessedDocument(Document("2", "B", "Microsoft"), "b", [Entity("Microsoft", "Companies", 0.9, ())], ["source/test"], relations=[Relation("Microsoft", "partner_of", "Apple")])
    upsert_document(second.document); save_result(second)
    with connect() as db:
        relation = db.execute("SELECT source_name,target_name FROM relations WHERE relation='partner_of'").fetchone()
    assert relation == ("Microsoft", "Apple Inc.")

def test_merge_entity_rewires_relations_and_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    from nayvadius.db import merge_entity
    with connect() as db:
        db.execute("INSERT INTO entities VALUES('Apple Inc.','Companies','Apple',0.8)")
        db.execute("INSERT INTO entities VALUES('Apple Computer','Companies','',0.7)")
        db.execute("INSERT INTO entity_aliases VALUES('apple','Apple Inc.','Companies')")
        db.execute("INSERT INTO entity_aliases VALUES('apple computer','Apple Computer','Companies')")
        db.execute("INSERT INTO relations VALUES('Apple Computer','acquired','Beats',0.7)")
        db.execute("INSERT INTO relations VALUES('Apple Inc.','acquired','Beats',0.9)")
        db.execute("INSERT INTO document_relations VALUES('doc-1','Apple Computer','acquired','Beats',0.7)")
        db.execute("INSERT INTO relation_evidence VALUES('doc-1','Apple Computer','acquired','Beats','rw-1','checked',CURRENT_TIMESTAMP)")
    assert merge_entity("Apple Inc.", "Apple Computer", "Companies") is True
    with connect() as db:
        entity = db.execute("SELECT name FROM entities WHERE entity_type='Companies' ORDER BY name").fetchall()
        rel = db.execute("SELECT source_name,target_name,confidence FROM relations").fetchall()
        ev = db.execute("SELECT source_name FROM relation_evidence").fetchall()
    assert entity == [("Apple Inc.",)]
    assert rel == [("Apple Inc.", "Beats", 0.9)]
    assert ev == [("Apple Inc.",)]

def test_abraham_refreshes_enrichment_when_content_is_unchanged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    doc = Document("same", "Same", "unchanged")
    first = ProcessedDocument(doc, "first", [Entity("Apple Inc.", "Companies", 0.8, ("Apple",))], ["source/test"])
    second = ProcessedDocument(doc, "second", [Entity("Microsoft", "Companies", 0.9, ())], ["source/test"])
    assert upsert_document(doc) is True
    save_result(first)
    assert upsert_document(doc, force=True) is True
    save_result(second)
    with connect() as db:
        names = db.execute("SELECT name FROM entities ORDER BY name").fetchall()
        payload = db.execute("SELECT payload FROM results WHERE document_id='same'").fetchone()[0]
    assert names == [("Apple Inc.",), ("Microsoft",)]
    assert '"summary": "second"' in payload

def test_prune_orphan_entities_removes_unused_aliases(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    from nayvadius.db import prune_orphan_entities
    with connect() as db:
        db.execute("INSERT INTO entities VALUES('Old Entity','Concepts','Old',0.6)")
        db.execute("INSERT INTO entity_aliases VALUES('old entity','Old Entity','Concepts')")
        db.execute("INSERT INTO entity_aliases VALUES('old','Old Entity','Concepts')")
    assert prune_orphan_entities() == 1
    with connect() as db:
        assert db.execute("SELECT * FROM entities").fetchall() == []
        assert db.execute("SELECT * FROM entity_aliases").fetchall() == []

def test_failure_queue_is_bounded_and_clears_on_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    from nayvadius.db import record_failure, failed_document_ids, clear_failure
    for _ in range(7):
        record_failure("bad-1", "boom", max_attempts=5)
    with connect() as db:
        row = db.execute("SELECT attempts,last_error FROM processing_failures WHERE document_id='bad-1'").fetchone()
    assert row == (5, "boom")
    assert failed_document_ids(5) == []
    clear_failure("bad-1")
    with connect() as db:
        assert db.execute("SELECT * FROM processing_failures").fetchall() == []
