from pathlib import Path
import hashlib
import sqlite3

from nayvadius.obsidian_audit import snapshot_vault
from nayvadius.reconciliation import build_db_reconciliation_plan


def _db(path, rows):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE documents(id TEXT, title TEXT, content_hash TEXT, source TEXT)")
        conn.execute("CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT)")
        conn.executemany("INSERT INTO documents VALUES(?,?,?,?)", rows)


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_unique_db_hash_move_is_auto(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)

    assert plan["summary"]["auto"] == 1
    item = plan["auto"][0]
    assert item["document_id"] == "doc-1"
    assert item["entities"] == [("Alice", "People")]


def test_ambiguous_db_hash_move_is_review(tmp_path: Path):
    db = tmp_path / "state.db"
    digest = _hash("same")
    _db(db, [("doc-1", "A", digest, "x"), ("doc-2", "B", digest, "y")])

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)

    assert plan["summary"]["auto"] == 0
    assert plan["review"][0]["db_check"] == "ambiguous DB content_hash match"


def test_missing_db_keeps_move_in_review(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), tmp_path / "missing.db")

    assert plan["summary"]["auto"] == 0
    assert plan["summary"]["review"] == 1
    assert plan["skipped"][0]["kind"] == "db"


def test_modified_note_keeps_previous_db_identity(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("before"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("before", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").write_text("after", encoding="utf-8")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)
    item = next(x for x in plan["review"] if x["kind"] == "modified")

    assert item["document_id"] == "doc-1"
    assert item["previous_db_entities"] == [("Alice", "People")]
    assert item["identity_status"] == "stale"


def test_added_note_reports_existing_db_match_as_review(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("new"), "readwise")])

    root = tmp_path / "vault"
    root.mkdir()
    previous = snapshot_vault(root)
    (root / "added.md").write_text("new", encoding="utf-8")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)
    item = plan["review"][0]

    assert item["kind"] == "added"
    assert item["document_id"] == "doc-1"
    assert item["db_check"] == "hash matches existing DB document; path identity is new"
