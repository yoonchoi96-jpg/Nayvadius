from pathlib import Path
from nayvadius.db_reconciliation_apply import apply_db_reconciliation_plan, verify_db_reconciliation_apply
from nayvadius.reconciliation import _fingerprint

def plan(root):
    import hashlib
    digest = hashlib.sha256(b"same").hexdigest()
    p={"title":"Nayvadius DB ↔ Vault Reconciliation Plan","plan_version":3,"status":"PLANNED",
       "previous_root":str(root),"current_root":str(root),"db_path":str(root/"state.db"),
       "auto":[{"action":"AUTO","kind":"move","source":"old.md","target":"20_Entities/People/New.md","hash":digest,
                "entity_resolution":{"resolved":[],"unresolved":[]},
                "wikilink_resolution":{"status":"checked","links":[],"unresolved":[]}}],
       "review":[],"skipped":[],"diff":{"summary":{"changed":1}},"db_summary":{},
       "summary":{"auto":1,"review":0,"skipped":0,"changed":1}}
    p["fingerprint"]=_fingerprint(p)
    return p

def test_dry_run(tmp_path: Path):
    (tmp_path/"old.md").write_text("same")
    r=apply_db_reconciliation_plan(tmp_path,plan(tmp_path))
    assert r["status"]=="PLANNED" and (tmp_path/"old.md").exists() and not (tmp_path/"new.md").exists()

def test_apply_creates_backup(tmp_path: Path):
    (tmp_path/"old.md").write_text("same")
    r=apply_db_reconciliation_plan(tmp_path,plan(tmp_path),apply=True)
    assert r["status"]=="APPLIED" and not (tmp_path/"old.md").exists()
    assert (tmp_path/"new.md").read_text()=="same"
    assert (tmp_path/r["backup_manifest"]).exists()

def test_changed_source_review(tmp_path: Path):
    (tmp_path/"old.md").write_text("changed")
    r=apply_db_reconciliation_plan(tmp_path,plan(tmp_path),apply=True)
    assert r["status"]=="REVIEW" and (tmp_path/"old.md").exists()

def test_target_never_overwritten(tmp_path: Path):
    (tmp_path/"old.md").write_text("same")
    (tmp_path/"new.md").write_text("different")
    r=apply_db_reconciliation_plan(tmp_path,plan(tmp_path),apply=True)
    assert r["status"]=="REVIEW" and (tmp_path/"new.md").read_text()=="different"


def test_wikilink_rewrite_on_apply(tmp_path: Path):
    (tmp_path / "old.md").write_text("same")
    (tmp_path / "note.md").write_text("See [[old]].")
    r = apply_db_reconciliation_plan(tmp_path, plan(tmp_path), apply=True)
    assert r["status"] == "APPLIED"
    assert (tmp_path / "note.md").read_text() == "See [[20_Entities/People/New]]."


def test_post_apply_verification(tmp_path: Path):
    (tmp_path / "old.md").write_text("same")
    r = apply_db_reconciliation_plan(tmp_path, plan(tmp_path), apply=True)
    v = verify_db_reconciliation_apply(tmp_path, r)
    assert v["status"] == "VERIFIED"
    assert v["checked"] == 1


def test_post_apply_verification_detects_tamper(tmp_path: Path):
    (tmp_path / "old.md").write_text("same")
    r = apply_db_reconciliation_plan(tmp_path, plan(tmp_path), apply=True)
    (tmp_path / "20_Entities/People/New.md").write_text("tampered")
    v = verify_db_reconciliation_apply(tmp_path, r)
    assert v["status"] == "FAIL"
    assert "target hash mismatch" in v["errors"][0]


def test_partial_move_failure_rolls_back_completed_moves(tmp_path: Path, monkeypatch):
    import hashlib
    from nayvadius import db_reconciliation_apply as apply_mod

    (tmp_path / "old.md").write_text("same")
    (tmp_path / "old2.md").write_text("same")
    p = plan(tmp_path)
    digest = hashlib.sha256(b"same").hexdigest()
    p["auto"].append({
        "action": "AUTO", "kind": "move", "source": "old2.md",
        "target": "20_Entities/People/New2.md", "hash": digest,
        "entity_resolution": {"resolved": [], "unresolved": []},
        "wikilink_resolution": {"status": "checked", "links": [], "unresolved": []},
    })
    p["summary"]["auto"] = 2
    p["diff"]["summary"]["changed"] = 2
    p["summary"]["changed"] = 2
    p["fingerprint"] = _fingerprint(p)

    original_rename = apply_mod.Path.rename
    calls = {"count": 0}

    def fail_second_rename(self, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected move failure")
        return original_rename(self, target)

    monkeypatch.setattr(apply_mod.Path, "rename", fail_second_rename)
    r = apply_mod.apply_db_reconciliation_plan(tmp_path, p, apply=True)
    assert r["status"] == "FAIL"
    assert r["rollback"]["status"] == "RESTORED"
    assert (tmp_path / "old.md").read_text() == "same"
    assert (tmp_path / "old2.md").read_text() == "same"
    assert not (tmp_path / "20_Entities/People/New.md").exists()
    assert not (tmp_path / "20_Entities/People/New2.md").exists()
