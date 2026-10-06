from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .processor import ENTITY_TYPES
from .obsidian_audit import LEGACY_ENTITY_TYPES, _iter_markdown, _parse_frontmatter, _sha256


ENTITY_ROOT_NAMES = ("20_Entities", "entities")
SYSTEM_DIRS = {"00_Inbox", "90_Dashboard", ".obsidian", ".nayvadius-backup"}


def _norm(value: str) -> str:
    return " ".join("".join(
        c if c.isalnum() else " " for c in unicodedata.normalize("NFKC", str(value or "")).casefold()
    ).split())


def _canonical_domain(value: str) -> str | None:
    value = LEGACY_ENTITY_TYPES.get(str(value or "").strip(), str(value or "").strip())
    return value if value in ENTITY_TYPES else None


def build_vault_organization_plan(root: str | Path) -> dict:
    """Build a deterministic relocation plan without semantic/LLM classification."""
    root = Path(root)
    moves, review, skipped, errors = [], [], [], []
    if not root.exists():
        return {"status": "FAIL", "root": str(root), "moves": [], "review": [],
                "skipped": [], "errors": [f"vault root does not exist: {root}"],
                "summary": {"scanned": 0, "auto": 0, "review": 0, "skipped": 0, "error": 1}}

    markdown_files = _iter_markdown(root)
    for path in markdown_files:
        rel = path.relative_to(root)
        parts = rel.parts
        if not parts or parts[0] in SYSTEM_DIRS:
            continue
        domain = None
        if len(parts) >= 2 and parts[0] in ENTITY_ROOT_NAMES:
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
            "action": "AUTO", "source": rel.as_posix(),
            "target": target.relative_to(root).as_posix(),
            "entity_type": domain, "file_hash": _sha256(path.read_bytes()),
        })

    status = "FAIL" if errors else ("REVIEW" if review else ("PLANNED" if moves else "CLEAN"))
    return {
        "title": "Nayvadius Vault Organization Plan", "status": status, "root": str(root),
        "moves": moves, "review": review, "skipped": skipped, "errors": errors,
        "summary": {"scanned": len(markdown_files), "auto": len(moves),
                    "review": len(review), "skipped": len(skipped), "error": len(errors)},
    }


def write_vault_organization_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_relative(root: Path, value: str) -> Path | None:
    candidate = Path(value)
    if candidate.is_absolute() or not value or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _rewrite_links_for_move(text: str, replacements: dict[str, str]) -> tuple[str, list[dict]]:
    from .obsidian_audit import _rewrite_target
    updated, _, links = _rewrite_target(text, replacements)
    return updated, links


def apply_vault_organization_plan(
    root: str | Path,
    plan: dict,
    backup_dir: str = ".nayvadius-backup",
    apply: bool = False,
) -> dict:
    """Apply only AUTO moves from a hash-validated plan, with backups and rollback."""
    root = Path(root)
    moves = [item for item in plan.get("moves", []) if isinstance(item, dict)]
    skipped = list(plan.get("review", [])) + list(plan.get("skipped", []))
    valid = []
    for item in moves:
        source = _safe_relative(root, item.get("source", ""))
        target = _safe_relative(root, item.get("target", ""))
        expected = item.get("file_hash")
        if source is None or target is None or source == target:
            skipped.append({"item": item, "reason": "invalid source or target"})
            continue
        if not source.is_file() or not expected or _sha256(source.read_bytes()) != expected:
            skipped.append({"item": item, "reason": "source changed since planning"})
            continue
        if target.exists():
            skipped.append({"item": item, "reason": "target now exists"})
            continue
        valid.append((item, source, target))

    if not apply:
        return {
            "status": "PLANNED" if valid else ("REVIEW" if skipped else "CLEAN"),
            "applied": [], "would_move": [{"source": i["source"], "target": i["target"]}
                                          for i, _, _ in valid],
            "skipped": skipped, "changed": 0,
        }

    if not valid:
        return {
            "status": "REVIEW" if skipped else "CLEAN",
            "applied": [],
            "skipped": skipped,
            "changed": 0,
        }

    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = root / backup_dir / "vault-organization" / operation
    manifest = []
    rewritten = {}
    try:
        for item, source, target in valid:
            backup = backup_root / source.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            backup.write_bytes(data)
            manifest.append({
                "operation": "vault_move",
                "original_path": source.relative_to(root).as_posix(),
                "new_path": target.relative_to(root).as_posix(),
                "backup_path": backup.relative_to(root).as_posix(),
                "original_hash": _sha256(data),
            })

        replacements = {}
        stems = {}
        for item, _, _ in valid:
            source = item["source"].removesuffix(".md")
            target = item["target"].removesuffix(".md")
            replacements[_norm(source)] = target
            stems.setdefault(_norm(Path(item["source"]).stem), []).append(Path(item["target"]).stem)
        for stem, targets in stems.items():
            if len(set(targets)) == 1:
                replacements[stem] = targets[0]

        valid_sources = {source.resolve() for _, source, _ in valid}
        for path in _iter_markdown(root):
            if path.resolve() in valid_sources:
                continue
            original = path.read_text(encoding="utf-8")
            updated, links = _rewrite_links_for_move(original, replacements)
            if updated != original:
                rewritten[path] = (original, updated, links)
                backup = backup_root / "rewrites" / path.relative_to(root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                original_bytes = original.encode("utf-8")
                backup.write_bytes(original_bytes)
                manifest.append({
                    "operation": "wikilink_rewrite",
                    "original_path": path.relative_to(root).as_posix(),
                    "new_path": path.relative_to(root).as_posix(),
                    "backup_path": backup.relative_to(root).as_posix(),
                    "original_hash": _sha256(original_bytes),
                    "new_hash": _sha256(updated.encode("utf-8")),
                })

        for path, (_, updated, _) in rewritten.items():
            temp = path.with_suffix(path.suffix + ".nayvadius.tmp")
            temp.write_text(updated, encoding="utf-8")
            temp.replace(path)
        for _, source, target in valid:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)

        manifest_path = backup_root / "manifest.json"
        manifest_path.write_text(json.dumps({"operations": manifest}, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        return {
            "status": "APPLIED" if valid else ("REVIEW" if skipped else "CLEAN"),
            "applied": [{"source": i["source"], "target": i["target"]} for i, _, _ in valid],
            "skipped": skipped, "changed": len(valid) + len(rewritten),
            "backup_manifest": manifest_path.relative_to(root).as_posix(),
        }
    except Exception as exc:
        for path, (original, _, _) in rewritten.items():
            path.write_text(original, encoding="utf-8")
        for _, source, target in valid:
            if target.exists() and not source.exists():
                target.rename(source)
        return {"status": "FAIL", "applied": [], "skipped": skipped, "changed": 0, "error": str(exc)}
