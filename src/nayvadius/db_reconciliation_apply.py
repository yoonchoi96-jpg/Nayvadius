from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .obsidian_audit import _iter_markdown, _sha256
from .reconciliation_guard import validate_db_reconciliation_plan


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


def apply_db_reconciliation_plan(root: str | Path, plan: dict, backup_dir: str = ".nayvadius-backup", apply: bool = False) -> dict:
    root = Path(root)
    validation = validate_db_reconciliation_plan(plan, root=root)
    if validation["status"] == "FAIL":
        return {"status": "REVIEW", "applied": [], "skipped": [], "changed": 0, "validation": validation}

    candidates, skipped = [], list(plan.get("review", [])) + list(plan.get("skipped", []))
    for item in plan.get("auto", []):
        source = _safe_relative(root, item.get("source", ""))
        target = _safe_relative(root, item.get("target", ""))
        expected = item.get("hash", "")
        if source is None or target is None or source == target:
            skipped.append({"item": item, "reason": "invalid source or target"}); continue
        if not source.is_file():
            skipped.append({"item": item, "reason": "source is missing"}); continue
        if len(expected) != 64 or _sha256(source.read_bytes()) != expected:
            skipped.append({"item": item, "reason": "source changed since reconciliation plan"}); continue
        if target.exists():
        if target.suffix.lower() != ".md":
            skipped.append({"item": item, "reason": "target is not markdown"}); continue
            skipped.append({"item": item, "reason": "target now exists"}); continue
        candidates.append((item, source, target))

    sources = [x[1] for x in candidates]
    targets = [x[2] for x in candidates]
    if len(set(sources)) != len(sources) or len(set(targets)) != len(targets) or set(sources) & set(targets):
        skipped.append({"reason": "planned source/target collision"})
        candidates = []

    if not apply:
        return {
            "status": "PLANNED" if candidates else ("REVIEW" if skipped else "CLEAN"),
            "applied": [], "would_move": [
                {"source": i["source"], "target": i["target"], "hash": i["hash"]}
                for i, _, _ in candidates
            ], "skipped": skipped, "changed": 0, "validation": validation,
        }

    if not candidates:
        return {"status": "REVIEW" if skipped else "CLEAN", "applied": [], "skipped": skipped, "changed": 0, "validation": validation}

    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = root / backup_dir / "db-reconciliation" / operation
    manifest = []
    rewritten = {}
    try:
        from .vault_organization import _rewrite_links_for_move
        replacements, stems = {}, {}
        for item, _, _ in candidates:
            replacements[item["source"].removesuffix(".md").casefold()] = item["target"].removesuffix(".md")
            stems.setdefault(Path(item["source"]).stem.casefold(), set()).add(Path(item["target"]).stem)
        for stem, values in stems.items():
            if len(values) == 1:
                replacements[stem] = next(iter(values))

        source_paths = {source.resolve() for _, source, _ in candidates}
        for item, source, target in candidates:
            backup = backup_root / source.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            backup.write_bytes(data)
            manifest.append({"operation": "move", "original_path": source.relative_to(root).as_posix(),
                             "new_path": target.relative_to(root).as_posix(), "backup_path": backup.relative_to(root).as_posix(),
                             "original_hash": _sha256(data)})

        for path in _iter_markdown(root):
            if path.resolve() in source_paths:
                continue
            original = path.read_text(encoding="utf-8")
            updated, links = _rewrite_links_for_move(original, replacements)
            if updated != original:
                backup = backup_root / "rewrites" / path.relative_to(root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(original, encoding="utf-8")
                rewritten[path] = original
                manifest.append({"operation": "wikilink_rewrite", "path": path.relative_to(root).as_posix(),
                                 "backup_path": backup.relative_to(root).as_posix(),
                                 "original_hash": _sha256(original.encode()), "new_hash": _sha256(updated.encode()),
                                 "rewritten_links": links})
                temp = path.with_suffix(path.suffix + ".nayvadius.tmp")
                temp.write_text(updated, encoding="utf-8")
                temp.replace(path)

        for _, source, target in candidates:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)

        manifest_path = backup_root / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"operations": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "APPLIED", "applied": [
            {"source": i["source"], "target": i["target"], "hash": i["hash"]} for i, _, _ in candidates
        ], "skipped": skipped, "changed": len(candidates) + len(rewritten),
        "backup_manifest": manifest_path.relative_to(root).as_posix(), "validation": validation}
    except Exception as exc:
        for path, original in rewritten.items():
            path.write_text(original, encoding="utf-8")
        for _, source, target in candidates:
            if target.exists() and not source.exists():
                target.rename(source)
        return {"status": "FAIL", "applied": [], "skipped": skipped, "changed": 0, "error": str(exc), "validation": validation}
