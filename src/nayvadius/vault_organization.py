from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from .processor import ENTITY_TYPES
from .obsidian_audit import LEGACY_ENTITY_TYPES, _iter_markdown, _parse_frontmatter, _sha256


ENTITY_ROOT_NAMES = ("20_Entities", "entities")
SYSTEM_DIRS = {"00_Inbox", "90_Dashboard", ".obsidian", ".nayvadius-backup"}
LEGACY_DIRS = {"Companies": "Organizations", "Brands": "Organizations", "Company": "Organizations", "Brand": "Organizations"}


def _norm(value: str) -> str:
    return " ".join("".join(
        c if c.isalnum() else " " for c in unicodedata.normalize("NFKC", str(value or "")).casefold()
    ).split())


def _canonical_domain(value: str) -> str | None:
    value = LEGACY_ENTITY_TYPES.get(str(value or "").strip(), str(value or "").strip())
    return value if value in ENTITY_TYPES else None


def build_vault_organization_plan(root: str | Path) -> dict:
    """Build a deterministic relocation plan without semantic/LLM classification.

    Only notes already carrying a recognized entity domain in their current path
    or frontmatter are eligible. Ambiguous/unrecognized notes are REVIEW, never AUTO.
    """
    root = Path(root)
    moves, review, skipped, errors = [], [], [], []
    if not root.exists():
        return {"status": "FAIL", "root": str(root), "moves": [], "review": [],
                "skipped": [], "errors": [f"vault root does not exist: {root}"],
                "summary": {"scanned": 0, "auto": 0, "review": 0, "skipped": 0, "error": 1}}

    for path in _iter_markdown(root):
        rel = path.relative_to(root)
        parts = rel.parts
        if not parts or parts[0] in SYSTEM_DIRS:
            continue
        domain = None
        source_root = None
        if len(parts) >= 2 and parts[0] in ENTITY_ROOT_NAMES:
            source_root = parts[0]
            domain = _canonical_domain(parts[1])
        fields, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
        front_domain = _canonical_domain(fields.get("entity_type") or fields.get("type"))
        if domain and front_domain and domain != front_domain:
            review.append({"path": rel.as_posix(), "action": "REVIEW",
                            "reason": "path domain conflicts with frontmatter entity type",
                            "path_domain": domain, "frontmatter_domain": front_domain})
            continue
        domain = domain or front_domain
        if not domain:
            if len(parts) >= 2 and parts[0] in ENTITY_ROOT_NAMES:
                review.append({"path": rel.as_posix(), "action": "REVIEW",
                               "reason": "entity folder is not a recognized canonical domain"})
            continue
        target = root / "20_Entities" / domain / path.name
        if path.resolve() == target.resolve():
            continue
        if target.exists():
            if _sha256(path.read_bytes()) == _sha256(target.read_bytes()):
                skipped.append({"path": rel.as_posix(), "action": "SKIP",
                                "reason": "target already exists with identical content",
                                "target": target.relative_to(root).as_posix()})
            else:
                review.append({"path": rel.as_posix(), "action": "REVIEW",
                               "reason": "target exists with different content",
                               "target": target.relative_to(root).as_posix()})
            continue
        moves.append({
            "action": "AUTO",
            "source": rel.as_posix(),
            "target": target.relative_to(root).as_posix(),
            "entity_type": domain,
            "file_hash": _sha256(path.read_bytes()),
        })

    actions = len(moves), len(review), len(skipped)
    status = "FAIL" if errors else ("REVIEW" if review else ("PLANNED" if moves else "CLEAN"))
    return {
        "title": "Nayvadius Vault Organization Plan",
        "status": status,
        "root": str(root),
        "moves": moves,
        "review": review,
        "skipped": skipped,
        "errors": errors,
        "summary": {"scanned": len(_iter_markdown(root)), "auto": actions[0],
                    "review": actions[1], "skipped": actions[2], "error": len(errors)},
    }


def write_vault_organization_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
