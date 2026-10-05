from pathlib import Path
from nayvadius.obsidian_audit import audit_vault, parse_wikilink

def test_obsidian_audit_passes_canonical_vault(tmp_path: Path):
    root = tmp_path / "vault"
    (root / "entities" / "People").mkdir(parents=True)
    (root / "entities" / "People" / "Taylor Swift.md").write_text("# Taylor Swift\\n", encoding="utf-8")
    (root / "_Knowledge Index.md").write_text("- [[Taylor Swift]]\\n", encoding="utf-8")
    report = audit_vault(root)
    assert report["status"] == "PASS"
    assert report["errors"] == []

def test_obsidian_audit_rejects_legacy_entity_domain(tmp_path: Path):
    root = tmp_path / "vault"
    (root / "entities" / "Companies").mkdir(parents=True)
    (root / "entities" / "Companies" / "Apple.md").write_text("# Apple\\n", encoding="utf-8")
    report = audit_vault(root)
    assert report["status"] == "FAIL"
    assert any("legacy/unknown entity domain" in x for x in report["errors"])

def test_obsidian_audit_reports_unresolved_links_as_warning(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("See [[Missing Entity]].\\n", encoding="utf-8")
    report = audit_vault(root)
    assert report["status"] == "PASS"
    assert report["warnings"][0]["kind"] == "unresolved_wikilink"


def test_entity_merge_plan_detects_same_normalized_name(tmp_path: Path):
    from nayvadius.obsidian_audit import build_entity_merge_plan
    root = tmp_path / "vault"
    (root / "entities" / "People").mkdir(parents=True)
    (root / "entities" / "People" / "David Bowie.md").write_text("# David Bowie\n", encoding="utf-8")
    (root / "entities" / "People" / "David  Bowie.md").write_text("# David Bowie\n", encoding="utf-8")
    plan = build_entity_merge_plan(root)
    assert plan["status"] == "REVIEW"
    assert plan["candidate_count"] == 1
    assert plan["candidates"][0]["action"] == "AUTO"


def test_entity_merge_apply_keeps_canonical_and_backs_up_duplicate(tmp_path: Path):
    from nayvadius.obsidian_audit import build_entity_merge_plan, apply_entity_merge_plan
    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "David Bowie.md").write_text("# canonical\n", encoding="utf-8")
    (people / "David  Bowie.md").write_text("# duplicate\n", encoding="utf-8")
    note = root / "note.md"
    note.write_text("[[David  Bowie]]\n", encoding="utf-8")

    plan = build_entity_merge_plan(root)
    preview = apply_entity_merge_plan(root, plan)
    assert preview["status"] == "PLANNED"
    assert (people / "David  Bowie.md").exists()
    assert preview["rewrites"][0]["rewrites"] == [
        {"from": "David  Bowie", "to": "David Bowie"}
    ]
    result = apply_entity_merge_plan(root, plan, apply=True)
    assert result["status"] == "APPLIED"
    assert (people / "David Bowie.md").exists()
    assert not (people / "David  Bowie.md").exists()
    assert (root / ".nayvadius-backup" / "entities" / "People" / "David  Bowie.md").exists()
    assert note.read_text(encoding="utf-8") == "[[David Bowie]]\n"
    manifest = (root / ".nayvadius-backup" / "manifest.json").read_text(encoding="utf-8")
    assert '"operation": "entity_merge"' in manifest
    assert apply_entity_merge_plan(root, plan, apply=True)["changed"] == 0


def test_review_only_merge_apply_is_a_noop(tmp_path: Path):
    from nayvadius.obsidian_audit import apply_entity_merge_plan

    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    note = people / "Possible Duplicate.md"
    note.write_text("# Keep unchanged\n", encoding="utf-8")
    plan = {
        "candidates": [{
            "action": "REVIEW",
            "candidates": ["entities/People/Possible Duplicate.md"],
        }]
    }

    result = apply_entity_merge_plan(root, plan, apply=True)
    assert result["status"] == "REVIEW"
    assert result["changed"] == 0
    assert note.read_text(encoding="utf-8") == "# Keep unchanged\n"
    assert not (root / ".nayvadius-backup").exists()


def test_merge_plan_classifies_metadata_conflicts_and_cross_domain_names(tmp_path: Path):
    from nayvadius.obsidian_audit import build_entity_merge_plan
    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "Jane Doe.md").write_text("---\nname: Jane Doe\nrole: author\n---\n", encoding="utf-8")
    (people / "jane-doe.md").write_text("---\nname: jane-doe\nrole: singer\n---\n", encoding="utf-8")
    orgs = root / "entities" / "Organizations"
    orgs.mkdir(parents=True)
    (orgs / "JANE DOE.md").write_text("# organization\n", encoding="utf-8")
    (people / "Jane Doe.md").write_text(
        "---\nname: Jane Doe\naliases: [Janie]\n---\n", encoding="utf-8"
    )
    (people / "Janie.md").write_text("# alias target\n", encoding="utf-8")
    (people / "John Doe.md").write_text(
        "---\nname: John Doe\naliases: [Same]\n---\n", encoding="utf-8"
    )
    (people / "Jon Doe.md").write_text(
        "---\nname: Jon Doe\naliases: [Same]\n---\n", encoding="utf-8"
    )

    plan = build_entity_merge_plan(root)
    assert plan["counts"]["REVIEW"] == 2
    assert plan["counts"]["SKIP"] == 2
    assert {candidate["action"] for candidate in plan["candidates"]} == {"REVIEW", "SKIP"}


def test_wikilink_parser_keeps_heading_and_display_components():
    parsed = parse_wikilink("Steve Jobs#Early life|Founder")
    assert parsed == {
        "target": "Steve Jobs", "heading": "Early life",
        "display": "Founder", "has_display": "True", "has_heading": "True",
    }


def test_normalize_dry_run_does_not_modify_and_apply_rewrites(tmp_path: Path):
    from nayvadius.obsidian_audit import normalize_vault
    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "David Bowie.md").write_text("# x\n", encoding="utf-8")
    note = root / "note.md"
    note.write_text("[[david bowie#Early life|Founder]] [[Unrelated]]\n", encoding="utf-8")
    dry = normalize_vault(root)
    assert dry["applied"] is False and dry["changes"]
    assert dry["changes"][0]["rewrites"] == [
        {"from": "david bowie#Early life|Founder", "to": "David Bowie#Early life|Founder"}
    ]
    assert note.read_text(encoding="utf-8") == "[[david bowie#Early life|Founder]] [[Unrelated]]\n"
    done = normalize_vault(root, apply=True)
    assert done["applied"] is True
    assert note.read_text(encoding="utf-8") == "[[David Bowie#Early life|Founder]] [[Unrelated]]\n"
    assert len(list((root / ".nayvadius-backup").rglob("*.md"))) == 1
    assert normalize_vault(root, apply=True)["changed"] == 0


def test_audit_reports_empty_notes_orphans_and_wikilink_forms(tmp_path: Path):
    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "Beyoncé.md").write_text("---\nname: Incorrect\naliases: [Queen B]\n---\n", encoding="utf-8")
    (people / "Orphan.md").write_text("", encoding="utf-8")
    note = root / "note.md"
    note.write_text(
        "[[Beyoncé#Music|B]] [[Queen B|Queen]] [[Missing]] [[note]]\n",
        encoding="utf-8",
    )
    report = audit_vault(root)
    kinds = {warning["kind"] for warning in report["warnings"]}
    assert any("empty entity file" in error for error in report["errors"])
    assert "frontmatter_name_mismatch" in kinds
    assert "alias_wikilink" in kinds
    assert "unresolved_wikilink" in kinds
    assert "self_wikilink" in kinds
    assert "orphan_entity" in kinds


def test_db_vault_maintenance_reports_both_sides_without_mutating(tmp_path: Path):
    import sqlite3
    from nayvadius.obsidian_audit import maintenance_report

    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "Alice.md").write_text("# Alice\n", encoding="utf-8")
    (root / "note.md").write_text("[[Alice]] [[Missing]]\n", encoding="utf-8")
    db_path = tmp_path / "state.db"
    db = sqlite3.connect(db_path)
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT);
    CREATE TABLE entity_sources(entity_name TEXT,entity_type TEXT);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT);
    """)
    db.execute("INSERT INTO entities VALUES('Bob','People','Robert')")
    db.execute("INSERT INTO relations VALUES('Bob','knows','Missing')")
    db.commit()
    db.close()

    report = maintenance_report(root, db_path)
    assert report["status"] == "REVIEW"
    assert report["summary"]["obsidian_only_entities"] == 1
    assert report["summary"]["db_only_entities"] == 1
    assert report["db_consistency"]["db_entities_missing_canonical_files"][0]["name"] == "Bob"
    assert report["db_consistency"]["db_relations_missing_db_endpoints"]
    assert report["summary"]["obsidian_only_entities"] == 1
    assert report["db_consistency"]["links_to_entities_absent_from_db"][0]["target"] == "Alice"
    assert report["summary"]["unresolved_links"] == 1


def test_audit_flags_wrong_domain_link_and_punctuation_only_entity(tmp_path: Path):
    root = tmp_path / "vault"
    (root / "entities" / "People").mkdir(parents=True)
    (root / "entities" / "People" / "Alice.md").write_text("# Alice\n", encoding="utf-8")
    (root / "entities" / "Concepts" / "!!!.md").parent.mkdir(parents=True)
    (root / "entities" / "Concepts" / "!!!.md").write_text("# Empty name\n", encoding="utf-8")
    (root / "note.md").write_text("[[entities/Places/Alice]]\n", encoding="utf-8")
    report = audit_vault(root)
    assert any("contains no letters or digits" in error for error in report["errors"])
    assert "wrong_entity_domain_link" in {warning["kind"] for warning in report["warnings"]}


def test_cli_exposes_apply_flag(capsys):
    import sys
    from nayvadius import cli
    sys.argv = ["nayvadius", "obsidian-normalize", "--help"]
    try:
        cli.main()
    except SystemExit:
        pass
    assert "--apply" in capsys.readouterr().out


def test_entity_merge_cli_is_dry_run_until_apply(tmp_path: Path, monkeypatch, capsys):
    import sys
    from nayvadius import cli
    from nayvadius.db import connect
    root = tmp_path / "vault"
    people = root / "entities" / "People"
    people.mkdir(parents=True)
    (people / "David Bowie.md").write_text("# David\n", encoding="utf-8")
    (people / "David  Bowie.md").write_text("# Duplicate\n", encoding="utf-8")
    db_path = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(db_path))
    with connect(db_path) as db:
        db.execute("INSERT INTO entities VALUES('David Bowie','People','',0.9)")
        db.execute("INSERT INTO entities VALUES('David  Bowie','People','',0.8)")

    sys.argv = ["nayvadius", "entity-merge-plan", "--output", str(root)]
    cli.main()
    sys.argv = ["nayvadius", "entity-merge-apply", "--output", str(root), "--db", str(db_path)]
    cli.main()
    assert (people / "David  Bowie.md").exists()
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM entities WHERE entity_type='People'").fetchone()[0] == 2

    sys.argv.append("--apply")
    cli.main()
    assert not (people / "David  Bowie.md").exists()
    with connect(db_path) as db:
        assert db.execute("SELECT name FROM entities WHERE entity_type='People'").fetchall() == [("David Bowie",)]


def test_maintenance_cli_writes_machine_readable_report(tmp_path: Path, capsys):
    import json
    import sys
    from nayvadius import cli
    from nayvadius.db import connect

    root = tmp_path / "vault"
    root.mkdir()
    db_path = tmp_path / "state.db"
    connect(db_path).close()
    sys.argv = ["nayvadius", "maintenance", "--output", str(root), "--db", str(db_path)]
    cli.main()
    report_path = root / "nayvadius_maintenance_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["title"] == "Nayvadius Maintenance Report"
    assert report["summary"]["scanned"] == 0
