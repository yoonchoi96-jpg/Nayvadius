from pathlib import Path
import sqlite3
import json
import hashlib

from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
    conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", _hash("same")))
    conn.commit()
    conn.close()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{"operation": "move", "original_path": "old.md", "new_path": "new.md", "original_hash": _hash("same")}]}))
    entry = {"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": _hash("same")}
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
    conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", _hash("same")))
    conn.commit()
    conn.close()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": _hash("same"),
    }]}))
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


def test_finalizer_reverifies_live_files_before_recording(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
        conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", "e" * 64))

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move",
        "original_path": "old.md",
        "new_path": "new.md",
        "original_hash": "e" * 64,
    }]}))
    (tmp_path / "new.md").write_text("wrong", encoding="utf-8")
    apply_result = {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [{"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": "e" * 64}],
    }

    result = finalize_db_reconciliation_provenance(
        db, tmp_path, apply_result, {"status": "VERIFIED"}, apply=True
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reconciliation_provenance'"
        ).fetchone() is None


def test_finalizer_is_transactional_across_multiple_entries(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
        conn.executemany(
            "INSERT INTO documents VALUES (?, ?)",
            [("doc-1", _hash("same")), ("doc-2", _hash("other"))],
        )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [
        {"operation": "move", "original_path": "old1.md", "new_path": "new1.md", "original_hash": _hash("same")},
        {"operation": "move", "original_path": "old2.md", "new_path": "new2.md", "original_hash": "f" * 64},
    ]}))
    (tmp_path / "new1.md").write_text("same", encoding="utf-8")
    (tmp_path / "new2.md").write_text("f", encoding="utf-8")
    apply_result = {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [
            {"document_id": "doc-1", "source": "old1.md", "target": "new1.md", "hash": _hash("same")},
            {"document_id": "doc-2", "source": "old2.md", "target": "new2.md", "hash": "f" * 64},
        ],
    }

    result = finalize_db_reconciliation_provenance(
        db, tmp_path, apply_result, {"status": "VERIFIED"}, apply=True
    )

    assert result["status"] == "REVIEW"
    assert result["recorded"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reconciliation_provenance'"
        ).fetchone() is None


def test_finalizer_reports_new_and_existing_provenance_separately(tmp_path: Path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, content_hash TEXT)")
        conn.execute("INSERT INTO documents VALUES (?, ?)", ("doc-1", _hash("same")))

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"operations": [{
        "operation": "move", "original_path": "old.md", "new_path": "new.md", "original_hash": _hash("same")
    }]}))
    (tmp_path / "new.md").write_text("same", encoding="utf-8")
    apply_result = {
        "status": "APPLIED",
        "backup_manifest": "manifest.json",
        "applied": [{"document_id": "doc-1", "source": "old.md", "target": "new.md", "hash": _hash("same")}],
    }

    first = finalize_db_reconciliation_provenance(db, tmp_path, apply_result, {"status": "VERIFIED"}, apply=True)
    second = finalize_db_reconciliation_provenance(db, tmp_path, apply_result, {"status": "VERIFIED"}, apply=True)

    assert first["recorded"] == 1
    assert first["already_recorded"] == 0
    assert second["recorded"] == 0
    assert second["already_recorded"] == 1
