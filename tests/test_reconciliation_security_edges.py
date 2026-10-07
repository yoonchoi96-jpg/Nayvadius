from pathlib import Path
import json
import sqlite3

from nayvadius.db_reconciliation_apply import verify_db_reconciliation_apply
from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def test_apply_verifier_rejects_non_sha256_applied_hash(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": "a" * 64,
    }]}))
    (tmp_path / "new.md").write_text("same", encoding="utf-8")

    result = verify_db_reconciliation_apply(
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": "manifest.json",
            "applied": [{
                "document_id": "doc-1",
                "source": "old.md",
                "target": "new.md",
                "hash": "not-a-sha256",
            }],
        },
    )

    assert result["status"] == "FAIL"
    assert any("invalid applied entry hash" in error for error in result["errors"])


def test_finalizer_rejects_non_string_manifest_path(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()

    result = finalize_db_reconciliation_provenance(
        db,
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": ["manifest.json"],
            "applied": [],
        },
        {"status": "VERIFIED"},
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0


def test_finalizer_rejects_unsupported_manifest_operation(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "delete",
        "path": "new.md",
    }]}))

    result = finalize_db_reconciliation_provenance(
        db,
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": "manifest.json",
            "applied": [],
        },
        {"status": "VERIFIED"},
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0


def test_finalizer_rejects_database_parent_symlink(tmp_path: Path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    db = real_dir / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")

    link_dir = tmp_path / "linked"
    link_dir.symlink_to(real_dir, target_is_directory=True)

    result = finalize_db_reconciliation_provenance(
        link_dir / "state.db",
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": "missing.json",
            "applied": [],
        },
        {"status": "VERIFIED"},
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0
    assert "symlink" in result["reason"]
