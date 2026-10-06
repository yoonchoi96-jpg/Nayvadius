from pathlib import Path
from nayvadius.db_reconciliation_apply import apply_db_reconciliation_plan
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
