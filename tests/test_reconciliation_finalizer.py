from pathlib import Path
import sqlite3

from nayvadius.reconciliation_finalizer import finalize_db_reconciliation_provenance


def test_finalizer_dry_run(tmp_path: Path):
    db = tmp_path / "state.db"
    db.touch()
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
