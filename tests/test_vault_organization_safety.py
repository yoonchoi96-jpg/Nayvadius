from pathlib import Path

from nayvadius.obsidian_audit import _sha256
from nayvadius.vault_organization import (
    apply_vault_organization_plan,
    build_vault_organization_plan,
)


def test_vault_organization_apply_is_dry_run_by_default(tmp_path: Path):
    root = tmp_path / "vault"
    source = root / "entities" / "Companies" / "Acme.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Acme\n", encoding="utf-8")

    plan = build_vault_organization_plan(root)
    result = apply_vault_organization_plan(root, plan)

    assert result["status"] == "PLANNED"
    assert source.exists()
    assert not (root / "20_Entities" / "Organizations" / "Acme.md").exists()
    assert not (root / ".nayvadius-backup").exists()


def test_vault_organization_apply_rejects_protected_source_from_tampered_plan(tmp_path: Path):
    root = tmp_path / "vault"
    protected = root / ".obsidian" / "app.md"
    protected.parent.mkdir(parents=True)
    protected.write_text("# do not move\n", encoding="utf-8")

    plan = {
        "moves": [{
            "action": "AUTO",
            "source": ".obsidian/app.md",
            "target": "20_Entities/Concepts/app.md",
            "file_hash": _sha256(protected.read_bytes()),
        }]
    }
    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert protected.exists()
    assert not (root / "20_Entities" / "Concepts" / "app.md").exists()
    assert not (root / ".nayvadius-backup").exists()


def test_vault_organization_apply_rejects_noncanonical_target_from_tampered_plan(tmp_path: Path):
    root = tmp_path / "vault"
    source = root / "entities" / "People" / "Alice.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Alice\n", encoding="utf-8")

    plan = {
        "moves": [{
            "action": "AUTO",
            "source": "entities/People/Alice.md",
            "target": "90_Dashboard/Alice.md",
            "file_hash": _sha256(source.read_bytes()),
        }]
    }
    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert source.exists()
    assert not (root / "90_Dashboard" / "Alice.md").exists()


def test_vault_organization_apply_rejects_target_directory_traversal(tmp_path: Path):
    root = tmp_path / "vault"
    source = root / "entities" / "People" / "Alice.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Alice\n", encoding="utf-8")

    plan = {
        "moves": [{
            "action": "AUTO",
            "source": "entities/People/Alice.md",
            "target": "20_Entities/People/../../outside.md",
            "file_hash": _sha256(source.read_bytes()),
        }]
    }
    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert source.exists()
    assert not (root.parent / "outside.md").exists()


def test_vault_organization_apply_rejects_plan_for_different_root(tmp_path: Path):
    root = tmp_path / "vault"
    source = root / "entities" / "People" / "Alice.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Alice\n", encoding="utf-8")

    plan = build_vault_organization_plan(root)
    other = tmp_path / "other-vault"
    other.mkdir()

    result = apply_vault_organization_plan(other, plan, apply=True)

    # A plan must never be silently redirected to another vault.
    assert result["status"] == "REVIEW"
    assert source.exists()


def test_vault_organization_apply_rejects_duplicate_targets_in_plan(tmp_path: Path):
    root = tmp_path / "vault"
    first = root / "entities" / "People" / "Alice.md"
    second = root / "entities" / "People" / "Bob.md"
    first.parent.mkdir(parents=True)
    first.write_text("# Alice\n", encoding="utf-8")
    second.write_text("# Bob\n", encoding="utf-8")

    target = "20_Entities/People/Same.md"
    plan = {
        "moves": [
            {"action": "AUTO", "source": "entities/People/Alice.md", "target": target, "file_hash": _sha256(first.read_bytes())},
            {"action": "AUTO", "source": "entities/People/Bob.md", "target": target, "file_hash": _sha256(second.read_bytes())},
        ]
    }
    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert first.exists()
    assert second.exists()
    assert not (root / target).exists()
    assert any(item.get("reason") == "duplicate source or target in plan" for item in result["skipped"])


def test_vault_organization_apply_rejects_source_target_collision_in_plan(tmp_path: Path):
    root = tmp_path / "vault"
    first = root / "entities" / "People" / "Alice.md"
    second = root / "20_Entities" / "People" / "Bob.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("# Alice\n", encoding="utf-8")
    second.write_text("# Bob\n", encoding="utf-8")

    plan = {
        "moves": [
            {"action": "AUTO", "source": "entities/People/Alice.md", "target": "20_Entities/People/Bob.md", "file_hash": _sha256(first.read_bytes())},
            {"action": "AUTO", "source": "20_Entities/People/Bob.md", "target": "20_Entities/People/Carol.md", "file_hash": _sha256(second.read_bytes())},
        ]
    }
    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert first.exists()
    assert second.exists()
    assert (root / "20_Entities" / "People" / "Bob.md").read_text(encoding="utf-8") == "# Bob\n"
    assert not (root / "20_Entities" / "People" / "Carol.md").exists()
    assert any(item.get("reason") == "move collision between planned source and target" for item in result["skipped"])



def test_vault_organization_apply_rejects_tampered_plan_fingerprint(tmp_path: Path):
    root = tmp_path / "vault"
    source = root / "entities" / "People" / "Alice.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Alice\n", encoding="utf-8")

    plan = build_vault_organization_plan(root)
    plan["moves"][0]["target"] = "20_Entities/People/Tampered.md"

    result = apply_vault_organization_plan(root, plan, apply=True)

    assert result["status"] == "REVIEW"
    assert source.exists()
    assert not (root / "20_Entities" / "People" / "Tampered.md").exists()


def test_vault_organization_apply_rejects_legacy_plan_schema(tmp_path: Path):
    root = tmp_path / "vault"
    result = apply_vault_organization_plan(root, {"moves": []}, apply=True)

    assert result["status"] == "REVIEW"
    assert result["skipped"][0]["reason"] == "invalid or legacy plan schema"
