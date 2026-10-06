
def test_change_repair_plan_auto_moves_and_reviews_other_changes(tmp_path: Path):
    from nayvadius.change_repair import build_change_repair_plan
    from nayvadius.obsidian_audit import snapshot_vault

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    (root / "changed.md").write_text("before", encoding="utf-8")
    (root / "deleted.md").write_text("gone", encoding="utf-8")
    previous = snapshot_vault(root)

    (root / "old.md").rename(root / "new.md")
    (root / "changed.md").write_text("after", encoding="utf-8")
    (root / "deleted.md").unlink()
    (root / "added.md").write_text("new", encoding="utf-8")

    plan = build_change_repair_plan(previous, snapshot_vault(root))
    assert plan["status"] == "REVIEW"
    assert plan["summary"] == {"auto": 1, "review": 3, "skipped": 0, "changed": 4}
    assert plan["auto"][0]["source"] == "old.md"
    assert plan["auto"][0]["target"] == "new.md"
    assert {item["kind"] for item in plan["review"]} == {"added", "deleted", "modified"}
    assert plan["fingerprint"]
