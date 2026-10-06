from pathlib import Path

from nayvadius.reconciliation_guard import validate_db_reconciliation_plan
from nayvadius.reconciliation import _fingerprint


def _plan(**overrides):
    plan = {
        "title": "Nayvadius DB ↔ Vault Reconciliation Plan",
        "plan_version": 3,
        "status": "PLANNED",
        "previous_root": "/tmp/vault",
        "current_root": "/tmp/vault",
        "db_path": "/tmp/state.db",
        "auto": [],
        "review": [],
        "skipped": [],
        "diff": {"summary": {"changed": 0}},
        "db_summary": {},
        "summary": {"auto": 0, "review": 0, "skipped": 0, "changed": 0},
    }
    plan.update(overrides)
    plan["fingerprint"] = _fingerprint(plan)
    return plan


def test_valid_plan_passes():
    result = validate_db_reconciliation_plan(_plan())
    assert result["status"] == "PASS"
    assert result["errors"] == []


def test_tampered_plan_fails_fingerprint():
    plan = _plan()
    plan["status"] = "REVIEW"
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("fingerprint mismatch" in error for error in result["errors"])


def test_auto_requires_move_and_sha256():
    plan = _plan(auto=[{
        "action": "AUTO",
        "kind": "added",
        "source": "old.md",
        "target": "new.md",
        "hash": "bad",
    }])
    plan["summary"]["auto"] = 1
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("is not a move" in error for error in result["errors"])
    assert any("hash is not a SHA-256" in error for error in result["errors"])


def test_auto_with_unresolved_graph_fails():
    plan = _plan(auto=[{
        "action": "AUTO",
        "kind": "move",
        "source": "old.md",
        "target": "new.md",
        "hash": "a" * 64,
        "entity_resolution": {"unresolved": [{"name": "Alice"}]},
        "wikilink_resolution": {"status": "checked", "unresolved": []},
    }])
    plan["summary"]["auto"] = 1
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("unresolved entity" in error for error in result["errors"])


def test_root_mismatch_fails():
    plan = _plan()
    result = validate_db_reconciliation_plan(plan, root=Path("/another/vault"))
    assert result["status"] == "FAIL"
    assert any("does not match requested root" in error for error in result["errors"])


def test_non_hex_hash_fails():
    plan = _plan(auto=[{"action": "AUTO", "kind": "move", "source": "old.md", "target": "new.md", "hash": "g" * 64}])
    plan["summary"]["auto"] = 1
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("SHA-256 hex" in error for error in result["errors"])

def test_protected_path_fails():
    plan = _plan(auto=[{"action": "AUTO", "kind": "move", "source": ".nayvadius-backup/old.md", "target": "new.md", "hash": "a" * 64}])
    plan["summary"]["auto"] = 1
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("protected path" in error for error in result["errors"])