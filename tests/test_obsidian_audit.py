from pathlib import Path
from nayvadius.obsidian_audit import audit_vault

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
