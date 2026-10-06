from pathlib import Path
import sqlite3
import json

from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def test_finalizer_dry_run(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
    manifest = tmp_path / ".nayvadius-backup/db-reconciliation/x/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"operations": [{"operation": "move", "original_path": "old.md", "new_path": "new.md", "original_hash": "a" * 64}]}))
    apply_result = {
        "status": "APPLIED",
        "backup_manifest": ".nayvadius-backup/db-reconciliation/x/manifest.json",
        "applied": [{"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": "a" * 64}],
    }
    verification = {"status": "VERIFIED"}
    result = finalize_db_reconciliation_provenance(db, tmp_path, apply_result, verification)
    assert result["status"] == "PLANNED"
    assert not list(tmp_path.glob("*.db-journal"))


def test_finalizer_requires_verification(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
    result = finalize_db_reconciliation_provenance(
        db, tmp_path,
        {"status": "APPLIED", "applied": []},
        {"status": "FAIL"},
        apply=True,
    )
    assert result["status"] == "REVIEW"


def test_finalizer_records_only_verified_apply(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
    conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", "b" * 64))
    conn.commit()
    conn.close()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{"operation": "move", "original_path": "old.md", "new_path": "new.md", "original_hash": "b" * 64}]}))
    entry = {"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": "b" * 64}
    result = finalize_db_reconciliation_provenance(
        db, tmp_path,
        {"status": "APPLIED", "backup_manifest": "manifest.json", "applied": [entry]},
        {"status": "VERIFIED"},
        apply=True,
    )
    assert result["status"] == "FINALIZED"
    assert result["recorded"] == 1

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT document_id,old_path,new_path,content_hash FROM reconciliation_provenance"
    ).fetchone()
    conn.close()
    assert row == ("doc-1", "old.md", "new.md", "b" * 64)


def test_finalizer_rejects_db_identity_mismatch_without_provenance(tmp_path: Path):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
    conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", "c" * 64))
    conn.commit()
    conn.close()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": "b" * 64,
    }]}))
    entry = {"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": "b" * 64}

    result = finalize_db_reconciliation_provenance(
        db, tmp_path,
        {"status": "APPLIED", "backup_manifest": "manifest.json", "applied": [entry]},
        {"status": "VERIFIED"},
        apply=True,
    )

    assert result["status"] == "REVIEW"
    conn = sqlite3.connect(db)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reconciliation_provenance'"
    ).fetchone()
    conn.close()
    assert tables is None


def test_finalizer_rejects_manifest_mismatch(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": "a" * 64,
    }]}))
    entry = {"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": "b" * 64}

    result = finalize_db_reconciliation_provenance(
        db, tmp_path,
        {"status": "APPLIED", "backup_manifest": "manifest.json", "applied": [entry]},
        {"status": "VERIFIED"},
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0


def test_finalizer_is_idempotent(tmp_path: Path):
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
    conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", "d" * 64))
    conn.commit()
    conn.close()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": "d" * 64,
    }]}))
    apply_result = {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [{
            "document_id": "doc-1",
            "source": "old.md",
            "target": "new.md",
            "hash": "d" * 64,
        }],
    }
    verification = {"status": "VERIFIED"}

    first = finalize_db_reconciliation_provenance(
        db, tmp_path, apply_result, verification, apply=True
    )
    second = finalize_db_reconciliation_provenance(
        db, tmp_path, apply_result, verification, apply=True
    )

    assert first["status"] == "FINALIZED"
    assert second["status"] == "FINALIZED"
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM reconciliation_provenance").fetchone()[0]
    conn.close()
    assert count == 1
