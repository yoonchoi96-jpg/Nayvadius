from pathlib import Path
import hashlib
import json
import sqlite3

from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def test_finalizer_rejects_database_parent_symlink_after_live_verification(tmp_path: Path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    db = real_dir / "state.db"
    content = "same"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
        conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", content_hash))

    (tmp_path / "new.md").write_text(content, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": content_hash,
    }]}))

    link_dir = tmp_path / "linked"
    link_dir.symlink_to(real_dir, target_is_directory=True)

    result = finalize_db_reconciliation_provenance(
        link_dir / "state.db",
        tmp_path,
        {
            "status": "APPLIED",
            "backup_manifest": "manifest.json",
            "applied": [{
                "document_id": "doc-1",
                "source": "old.md",
                "target": "new.md",
                "hash": content_hash,
            }],
        },
        {"status": "VERIFIED"},
        apply=True,
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reconciliation_provenance'"
        ).fetchone() is None
