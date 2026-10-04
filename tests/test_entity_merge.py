from pathlib import Path

from nayvadius.db import connect, merge_entity


def test_entity_merge_is_same_type_and_audited(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    db_path = tmp_path / "state.db"
    db = connect(db_path)
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Acme Inc.", "Organizations", "Acme", 0.9))
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Acme", "Organizations", "", 0.8))
    db.execute("INSERT INTO documents(id,title,content_hash,source,status) VALUES(?,?,?,?,?)", ("d1", "doc", "h", "abraham", "done"))
    db.execute("INSERT INTO document_entities VALUES(?,?,?,?)", ("d1", "Acme", "Organizations", 0.8))
    db.execute("INSERT INTO entity_sources VALUES(?,?,?,?)", ("Acme", "Organizations", "abraham", "d1"))
    db.commit()
    db.close()

    assert merge_entity("Acme Inc.", "Acme", "Organizations", reason="explicit_alias")

    db = connect(db_path)
    assert db.execute("SELECT name FROM entities WHERE entity_type='Organizations' ORDER BY name").fetchall() == [("Acme Inc.",)]
    assert db.execute("SELECT entity_name FROM document_entities").fetchall() == [("Acme Inc.",)]
    assert db.execute("SELECT entity_name FROM entity_sources").fetchall() == [("Acme Inc.",)]
    assert db.execute("SELECT canonical_name,duplicate_name,entity_type,reason FROM entity_merge_log").fetchall() == [
        ("Acme Inc.", "Acme", "Organizations", "explicit_alias")
    ]
    db.close()


def test_entity_merge_rejects_unknown_reason(tmp_path: Path):
    db = connect(tmp_path / "state.db")
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("A", "Organizations", "", 1.0))
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("B", "Organizations", "", 1.0))
    db.commit()
    db.close()

    try:
        merge_entity("A", "B", "Organizations", reason="guess")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown merge reason must be rejected")


def test_entity_merge_preserves_existing_document_link_confidence(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(tmp_path / "state.db"))
    db_path = tmp_path / "state.db"
    db = connect(db_path)
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Canonical", "People", "", 0.9))
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Alias", "People", "", 0.8))
    db.execute("INSERT INTO documents(document_id,title,content_hash,source,status) VALUES(?,?,?,?,?)", ("d1", "doc", "h", "abraham", "done"))
    db.execute("INSERT INTO document_entities VALUES(?,?,?,?)", ("d1", "Canonical", "People", 0.4))
    db.execute("INSERT INTO document_entities VALUES(?,?,?,?)", ("d1", "Alias", "People", 0.8))
    db.commit()
    db.close()

    assert merge_entity("Canonical", "Alias", "People", reason="explicit_alias")

    db = connect(db_path)
    assert db.execute(
        "SELECT document_id,entity_name,confidence FROM document_entities"
    ).fetchall() == [("d1", "Canonical", 0.8)]
    db.close()
