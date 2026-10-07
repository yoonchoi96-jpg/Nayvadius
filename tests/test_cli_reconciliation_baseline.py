from pathlib import Path
import json
import sys

import nayvadius.cli as cli


def test_db_reconcile_plan_does_not_advance_pending_baseline(tmp_path: Path, monkeypatch):
    snapshot_path = tmp_path / "vault_snapshot.json"
    baseline = {
        "version": 1,
        "root": str(tmp_path),
        "files": {"old.md": {"hash": "a" * 64, "size": 1}},
    }
    snapshot_path.write_text(json.dumps(baseline), encoding="utf-8")

    current = {
        "version": 1,
        "root": str(tmp_path),
        "files": {"new.md": {"hash": "a" * 64, "size": 1}},
    }
    plan = {
        "status": "REVIEW",
        "auto": [],
        "review": [{"source": "old.md", "target": "new.md"}],
        "skipped": [],
    }

    monkeypatch.setattr(cli, "build_live_db_reconciliation_plan", lambda previous, root, db: (current, plan))
    monkeypatch.setattr(cli, "write_db_reconciliation_plan", lambda plan, path: None)

    monkeypatch.setattr(sys, "argv", [
        "nayvadius",
        "db-reconcile-plan",
        "--output", str(tmp_path),
        "--db", str(tmp_path / "state.db"),
    ])

    cli.main()

    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == baseline


def test_db_reconcile_plan_advances_baseline_when_clean(tmp_path: Path, monkeypatch):
    snapshot_path = tmp_path / "vault_snapshot.json"
    baseline = {
        "version": 1,
        "root": str(tmp_path),
        "files": {"old.md": {"hash": "a" * 64, "size": 1}},
    }
    snapshot_path.write_text(json.dumps(baseline), encoding="utf-8")

    current = {
        "version": 1,
        "root": str(tmp_path),
        "files": {"new.md": {"hash": "b" * 64, "size": 1}},
    }
    plan = {"status": "CLEAN", "auto": [], "review": [], "skipped": []}

    monkeypatch.setattr(cli, "build_live_db_reconciliation_plan", lambda previous, root, db: (current, plan))
    monkeypatch.setattr(cli, "write_db_reconciliation_plan", lambda plan, path: None)

    monkeypatch.setattr(sys, "argv", [
        "nayvadius",
        "db-reconcile-plan",
        "--output", str(tmp_path),
        "--db", str(tmp_path / "state.db"),
    ])

    cli.main()

    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == current
