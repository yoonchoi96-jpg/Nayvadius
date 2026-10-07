from pathlib import Path
import hashlib
import json
import sqlite3

from nayvadius.db_reconciliation_apply import (
    apply_db_reconciliation_plan,
    verify_db_reconciliation_apply,
)
from nayvadius.reconciliation import build_db_reconciliation_plan, snapshot_vault
from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance
from nayvadius.reconciliation_guard import validate_db_reconciliation_plan


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_full_db_vault_reconciliation_lifecycle(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    db = tmp_path / "state.db"

    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE documents(id TEXT PRIMARY KEY, title TEXT, content_hash TEXT, source TEXT)"
        )
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?)",
            ("doc-1", "Note", _hash("same"), "readwise"),
        )

    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)

    (root / "old.md").rename(root / "new.md")
    current = snapshot_vault(root)
    plan = build_db_reconciliation_plan(previous, current, db, vault_root=root)

    assert plan["summary"] == {"auto": 1, "review": 0, "skipped": 0, "changed": 1}

    guard = validate_db_reconciliation_plan(plan, root=root)
    assert guard["status"] == "PASS"
    assert guard["auto"] == 1

    dry_run = apply_db_reconciliation_plan(root, plan, apply=False)
    assert dry_run["status"] == "PLANNED"
    assert dry_run["changed"] == 0
    assert (root / "new.md").is_file()

    # Recreate the move from the snapshot state for the actual apply stage.
    (root / "new.md").rename(root / "old.md")
    applied = apply_db_reconciliation_plan(root, plan, apply=True)

    assert applied["status"] == "APPLIED"
    assert applied["changed"] == 1
    assert not (root / "old.md").exists()
    assert (root / "new.md").read_text(encoding="utf-8") == "same"

    verification = verify_db_reconciliation_apply(root, applied)
    assert verification["status"] == "VERIFIED"
    assert verification["checked"] == 1

    result = finalize_db_reconciliation_provenance(
        db, root, applied, verification, apply=True
    )
    assert result["status"] == "FINALIZED"
    assert result["recorded"] == 1

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT document_id, content_hash, old_path, new_path, manifest_path "
            "FROM reconciliation_provenance"
        ).fetchone()

    assert row == (
        "doc-1",
        _hash("same"),
        "old.md",
        "new.md",
        applied["backup_manifest"],
    )



def test_verify_rejects_unhashable_applied_entry_without_crashing(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": _hash("same"),
    }]}), encoding="utf-8")
    (tmp_path / "new.md").write_text("same", encoding="utf-8")

    result = verify_db_reconciliation_apply(
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": "manifest.json",
            "applied": [{"source": [], "target": {}, "hash": "same"}],
        },
    )

    assert result["status"] == "FAIL"
    assert "invalid applied entry fields" in result["errors"]
