from pathlib import Path
import sqlite3

from nayvadius.obsidian_audit import snapshot_vault
from nayvadius.reconciliation import build_db_reconciliation_plan


def test_db_reconciliation_plan_is_conservative(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    (root / "changed.md").write_text("before", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")
    (root / "changed.md").write_text("after", encoding="utf-8")
    (root / "added.md").write_text("new", encoding="utf-8")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), tmp_path / "missing.db")
    assert plan["status"] == "REVIEW"
    assert plan["summary"]["auto"] == 1
    assert plan["summary"]["review"] == 2
    assert plan["skipped"][0]["kind"] == "db"
    assert plan["fingerprint"]


def test_db_reconciliation_reads_entity_records(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT)")
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")
    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("x", encoding="utf-8")
    snap = snapshot_vault(root)
    plan = build_db_reconciliation_plan(snap, snap, db)
    assert plan["status"] == "CLEAN"
    assert plan["db_summary"]["entity_identities"] == 1
