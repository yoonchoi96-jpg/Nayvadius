from pathlib import Path
import sqlite3

from nayvadius.obsidian_audit import snapshot_vault
from nayvadius.reconciliation import build_db_reconciliation_plan


def test_unique_db_hash_move_is_auto(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE documents(id TEXT PRIMARY KEY, title TEXT, content_hash TEXT, source TEXT)"
        )
        conn.execute(
            "CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT)"
        )

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)

    with sqlite3.connect(db) as conn:
        import hashlib
        digest = hashlib.sha256(b"same").hexdigest()
        conn.execute("INSERT INTO documents VALUES('doc-1','Note',?,'readwise')", (digest,))
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    (root / "old.md").rename(root / "new.md")
    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)

    assert plan["summary"]["auto"] == 1
    item = plan["auto"][0]
    assert item["document_id"] == "doc-1"
    assert item["entities"] == [("Alice", "People")]


def test_ambiguous_db_hash_move_is_review(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents(id TEXT, title TEXT, content_hash TEXT, source TEXT)")
        import hashlib
        digest = hashlib.sha256(b"same").hexdigest()
        conn.execute("INSERT INTO documents VALUES('doc-1','A',?,'x')", (digest,))
        conn.execute("INSERT INTO documents VALUES('doc-2','B',?,'y')", (digest,))

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)
    assert plan["summary"]["auto"] == 0
    assert plan["review"][0]["db_check"] == "ambiguous DB content_hash match"
