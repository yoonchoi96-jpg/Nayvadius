from pathlib import Path
import hashlib
import json
import sqlite3

from nayvadius.db_reconciliation_apply import verify_db_reconciliation_apply
from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_verifier_rejects_non_sha256_applied_entry_hash(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": _hash("same"),
    }]}))
    (tmp_path / "new.md").write_text("same", encoding="utf-8")
    result = verify_db_reconciliation_apply(tmp_path, {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [{
            "document_id": "doc-1",
            "source": "old.md",
            "target": "new.md",
            "hash": "not-a-sha256",
        }],
    })
    assert result["status"] == "FAIL"
    assert any("invalid applied entry hash" in error for error in result["errors"])


def test_finalizer_rejects_database_parent_symlink(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    db = real / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
        conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", _hash("same")))

    link = tmp_path / "db-link"
    link.symlink_to(real, target_is_directory=True)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": _hash("same"),
    }]}))
    (tmp_path / "new.md").write_text("same", encoding="utf-8")

    apply_result = {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [{
            "document_id": "doc-1",
            "source": "old.md",
            "target": "new.md",
            "hash": _hash("same"),
        }],
    }
    result = finalize_db_reconciliation_provenance(
        link / "state.db", tmp_path, apply_result, {"status": "VERIFIED"}, apply=True
    )
    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0
