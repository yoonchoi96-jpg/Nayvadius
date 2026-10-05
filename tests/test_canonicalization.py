from pathlib import Path
from nayvadius.models import Document, Entity, ProcessedDocument, Relation
from nayvadius.store import upsert_document, save_result
from nayvadius.db import connect

def test_aliases_canonicalize_same_entity(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple Inc."), "a", [Entity("Apple Inc.", "Organizations", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    second = ProcessedDocument(Document("2", "B", "Apple"), "b", [Entity("Apple", "Organizations", 0.9, ("Apple Inc.",))], ["source/test"], relations=[Relation("Apple", "related_to", "Apple")])
    upsert_document(second.document); save_result(second)
    with connect() as db:
        entities = db.execute("SELECT name,entity_type FROM entities ORDER BY name").fetchall()
        aliases = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY alias").fetchall()
        relation = db.execute("SELECT source_name,target_name FROM relations").fetchone()
    assert entities == [("Apple Inc.", "Organizations")]
    assert ("apple", "Apple Inc.", "Organizations") in aliases
    assert ("apple inc.", "Apple Inc.", "Organizations") in aliases
    assert relation == ("Apple Inc.", "Apple Inc.")

def test_conflicting_alias_does_not_overwrite_existing_mapping(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple"), "a", [Entity("Apple Inc.", "Organizations", 0.9, ("Apple",))], ["source/test"])
    second = ProcessedDocument(Document("2", "B", "Apple"), "b", [Entity("Apple Music", "Organizations", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    upsert_document(second.document); save_result(second)
    with connect() as db:
        rows = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases WHERE alias='apple'").fetchall()
    assert rows == [("apple", "Apple Inc.", "Organizations")]

def test_relation_resolves_historical_alias(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    first = ProcessedDocument(Document("1", "A", "Apple Inc."), "a", [Entity("Apple Inc.", "Organizations", 0.9, ("Apple",))], ["source/test"])
    upsert_document(first.document); save_result(first)
    second = ProcessedDocument(Document("2", "B", "Microsoft"), "b", [Entity("Microsoft", "Organizations", 0.9, ())], ["source/test"], relations=[Relation("Microsoft", "partner_of", "Apple")])
    upsert_document(second.document); save_result(second)
    with connect() as db:
        relation = db.execute("SELECT source_name,target_name FROM relations WHERE relation='partner_of'").fetchone()
    assert relation == ("Microsoft", "Apple Inc.")

def test_merge_entity_rewires_relations_and_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    from nayvadius.db import merge_entity
    with connect() as db:
        db.execute("INSERT INTO entities VALUES('Apple Inc.','Organizations','Apple',0.8)")
        db.execute("INSERT INTO entities VALUES('Apple Computer','Organizations','',0.7)")
        db.execute("INSERT INTO entity_aliases VALUES('apple','Apple Inc.','Organizations')")
        db.execute("INSERT INTO entity_aliases VALUES('apple computer','Apple Computer','Organizations')")
        db.execute("INSERT INTO relations VALUES('Apple Computer','acquired','Beats',0.7)")
        db.execute("INSERT INTO relations VALUES('Apple Inc.','acquired','Beats',0.9)")
        db.execute("INSERT INTO document_relations VALUES('doc-1','Apple Computer','acquired','Beats',0.7)")
        db.execute("INSERT INTO relation_evidence VALUES('doc-1','Apple Computer','acquired','Beats','rw-1','checked',CURRENT_TIMESTAMP)")
    assert merge_entity("Apple Inc.", "Apple Computer", "Organizations") is True
    with connect() as db:
        entity = db.execute("SELECT name FROM entities WHERE entity_type='Organizations' ORDER BY name").fetchall()
        rel = db.execute("SELECT source_name,target_name,confidence FROM relations").fetchall()
        ev = db.execute("SELECT source_name FROM relation_evidence").fetchall()
    assert entity == [("Apple Inc.",)]
    assert rel == [("Apple Inc.", "Beats", 0.9)]
    assert ev == [("Apple Inc.",)]

def test_abraham_refreshes_enrichment_when_content_is_unchanged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    doc = Document("same", "Same", "unchanged")
    first = ProcessedDocument(doc, "first", [Entity("Apple Inc.", "Organizations", 0.8, ("Apple",))], ["source/test"])
    second = ProcessedDocument(doc, "second", [Entity("Microsoft", "Organizations", 0.9, ())], ["source/test"])
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


def _save(doc_id, entities, relations=()):
    r = ProcessedDocument(Document(doc_id, doc_id, doc_id), doc_id, list(entities), ["source/test"], relations=list(relations))
    upsert_document(r.document); save_result(r)


def _names(etype=None):
    with connect() as db:
        return [r[0] for r in db.execute("SELECT name FROM entities ORDER BY name").fetchall()]


def _bowie(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("David Bowie", "People", 0.9, ("David Robert Jones", "Bowie"))])


def test_alias_canonicalization(tmp_path, monkeypatch):
    _bowie(tmp_path, monkeypatch)
    _save("2", [Entity("David Robert Jones", "People", 0.9, ())])
    assert _names() == ["David Bowie"]


def test_case_insensitive_and_whitespace_exact_name(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("David Bowie", "People", 0.9, ())])
    _save("2", [Entity("david bowie", "People", 0.9, ())])
    _save("3", [Entity("David  Bowie", "People", 0.9, ())])
    _save("4", [Entity("DAVID BOWIE", "People", 0.9, ())])
    assert _names() == ["David Bowie"]


def test_entity_type_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("Apple", "Organizations", 0.9, ())])
    _save("2", [Entity("apple", "Products", 0.9, ())])
    with connect() as db:
        rows = db.execute("SELECT name,entity_type FROM entities ORDER BY entity_type").fetchall()
    assert rows == [("Apple", "Organizations"), ("apple", "Products")]


def test_ambiguous_alias_keeps_incoming_name(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("Apple Inc.", "Organizations", 0.9, ()), Entity("Apple Music", "Organizations", 0.9, ())])
    with connect() as db:
        db.execute("INSERT INTO entity_aliases VALUES('x alias','Apple Inc.','Organizations')")
        db.execute("INSERT INTO entity_aliases VALUES('y alias','Apple Music','Organizations')")
    _save("2", [Entity("New Thing", "Organizations", 0.9, ("X Alias", "Y Alias"))])
    assert "New Thing" in _names()


def test_relation_and_save_result_integration(tmp_path, monkeypatch):
    _bowie(tmp_path, monkeypatch)
    _save("2", [Entity("David Robert Jones", "People", 0.9, ("David Bowie",)), Entity("Berlin", "Places", 0.9, ())],
          [Relation("David Robert Jones", "lived_in", "Berlin")])
    _save("3", [Entity("Berlin", "Places", 0.9, ())], [Relation("Bowie", "visited", "Berlin")])
    with connect() as db:
        rels = db.execute("SELECT source_name,relation,target_name FROM relations ORDER BY relation").fetchall()
        docs = db.execute("SELECT entity_name FROM document_entities WHERE document_id='2' AND entity_type='People'").fetchall()
        aliases = {r[0] for r in db.execute("SELECT alias FROM entity_aliases WHERE canonical_name='David Bowie'")}
        src = db.execute("SELECT entity_name FROM entity_sources WHERE document_id='2' AND entity_type='People'").fetchall()
    assert rels == [("David Bowie", "lived_in", "Berlin"), ("David Bowie", "visited", "Berlin")]
    assert docs == [("David Bowie",)] and src == [("David Bowie",)]
    assert {"bowie", "david robert jones", "david bowie"} <= aliases
    assert "David Robert Jones" not in _names()


def test_alias_persistence_and_relation_semantics(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("David Bowie", "People", 0.9, ("Bowie", "David Robert Jones"))])
    _save("2", [Entity("David Robert Jones", "People", 0.9, ("Ziggy Stardust",)), Entity("Brian Eno", "People", 0.9, ())],
          [Relation("David Robert Jones", "collaborated_with", "Brian Eno")])
    with connect() as db:
        row = db.execute("SELECT name,aliases FROM entities WHERE name='David Bowie'").fetchone()
        rel = db.execute("SELECT source_name,relation,target_name FROM document_relations WHERE document_id='2'").fetchone()
    assert "Ziggy Stardust" in row[1] and "Bowie" in row[1]
    assert rel == ("David Bowie", "collaborated_with", "Brian Eno")


def test_unicode_and_punctuation_normalized_entity_names(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("AC/DC", "Organizations", 0.9, ())])
    _save("2", [Entity("ＡＣ／ＤＣ", "Organizations", 0.8, ())])
    with connect() as db:
        names = db.execute(
            "SELECT name FROM entities WHERE entity_type='Organizations'"
        ).fetchall()
    assert names == [("AC/DC",)]


def test_exact_canonical_name_precedes_conflicting_alias_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("Apple Inc.", "Organizations", 0.9, ("Apple",))])
    _save("2", [Entity("Apple Music", "Organizations", 0.9, ("Apple Music",))])
    _save("3", [Entity("Apple Inc.", "Organizations", 1.0, ("Apple Music",))])
    assert _names() == ["Apple Inc.", "Apple Music"]


def test_explicit_alias_resolves_entity_name_variant(tmp_path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    _save("1", [Entity("The Beatles", "People", 0.9, ("Beatles",))])
    _save("2", [Entity("Beatles", "People", 0.9, ())])
    assert _names() == ["The Beatles"]
