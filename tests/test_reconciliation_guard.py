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

def test_non_object_resolution_metadata_fails():
    plan = _plan(auto=[{
        "action": "AUTO",
        "kind": "move",
        "source": "old.md",
        "target": "new.md",
        "hash": "a" * 64,
        "entity_resolution": [],
        "wikilink_resolution": {"unresolved": []},
    }])
    plan["summary"]["auto"] = 1
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("entity_resolution must be an object" in e for e in result["errors"])


def test_invalid_fingerprint_format_fails():
    plan = _plan()
    plan["fingerprint"] = "g" * 64
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("fingerprint is not a SHA-256 hex string" in e for e in result["errors"])


def test_duplicate_auto_entries_fail():
    item = {
        "action": "AUTO",
        "kind": "move",
        "source": "old.md",
        "target": "new.md",
        "hash": "a" * 64,
    }
    plan = _plan(auto=[item, dict(item)])
    plan["summary"]["auto"] = 2
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("duplicate reconciliation entries" in e for e in result["errors"])


def test_summary_must_be_object():
    plan = _plan(summary=[])
    plan["fingerprint"] = _fingerprint(plan)
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("summary must be an object" in e for e in result["errors"])



def test_review_and_skipped_entries_must_be_objects():
    plan = _plan(review=["bad"], skipped=["bad"])
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("review[0] must be an object" in e for e in result["errors"])
    assert any("skipped[0] must be an object" in e for e in result["errors"])


def test_diff_and_db_summary_must_be_objects():
    plan = _plan(diff=[], db_summary=[])
    result = validate_db_reconciliation_plan(plan)
    assert result["status"] == "FAIL"
    assert any("diff must be an object" in e for e in result["errors"])
    assert any("db_summary must be an object" in e for e in result["errors"])
