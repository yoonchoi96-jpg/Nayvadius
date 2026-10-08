from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .obsidian_audit import _iter_markdown, _sha256
from .reconciliation_guard import validate_db_reconciliation_plan


def _safe_relative(root: Path, value: str) -> Path | None:
    if not isinstance(value, str):
        return None
    candidate = Path(value)
    if candidate.is_absolute() or not value or ".." in candidate.parts:
        return None
    root_resolved = root.resolve()
    current = root_resolved
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            return None
    resolved = current.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None
    return resolved


def _contains_symlink(root: Path, path: Path) -> bool:
    """Reject symlink path components that could redirect a mutation."""
    try:
        relative = path.relative_to(root.resolve())
    except ValueError:
        return True
    current = root.resolve()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def apply_db_reconciliation_plan(root: str | Path, plan: dict, backup_dir: str = ".nayvadius-backup", apply: bool = False) -> dict:
    root = Path(root)
    if root.is_symlink() or not root.exists() or not root.is_dir():
        return {"status": "REVIEW", "applied": [], "skipped": [], "changed": 0,
                "reason": "vault root is missing, not a directory, or is a symlink"}
    backup_candidate = Path(backup_dir)
    if backup_candidate.is_absolute() or not backup_dir or ".." in backup_candidate.parts:
        return {"status": "REVIEW", "applied": [], "skipped": [], "changed": 0,
                "reason": "backup directory is not a safe relative path"}
    backup_resolved = (root / backup_candidate).resolve()
    if _contains_symlink(root, root / backup_candidate):
        return {"status": "REVIEW", "applied": [], "skipped": [], "changed": 0,
                "reason": "backup directory contains a symlink"}
    try:
        backup_resolved.relative_to(root.resolve())
    except ValueError:
        return {"status": "REVIEW", "applied": [], "skipped": [], "changed": 0,
                "reason": "backup directory escapes vault root"}
    validation = validate_db_reconciliation_plan(plan, root=root)
    # Accept older producer payloads that carry only diff.summary while
    # preserving the strict guard for direct callers.
    if validation["status"] == "FAIL" and isinstance(plan.get("diff"), dict):
        diff = dict(plan["diff"])
        if isinstance(diff.get("summary"), dict) and any(k not in diff for k in ("added", "deleted", "modified", "moved")):
            normalized = dict(plan)
            normalized_diff = dict(diff)
            summary = dict(normalized_diff["summary"])
            counts = {"added": 0, "deleted": 0, "modified": 0, "moved": 0}
            auto_moves = sum(1 for item in plan.get("auto", []) if isinstance(item, dict) and item.get("kind") == "move")
            review_moves = sum(1 for item in plan.get("review", []) if isinstance(item, dict) and item.get("kind") == "move")
            counts["moved"] = auto_moves + review_moves
            for key, value in counts.items():
                normalized_diff[key] = [{} for _ in range(value)]
                summary.setdefault(key, value)
            normalized_diff["summary"] = summary
            normalized["diff"] = normalized_diff
            normalized["fingerprint"] = __import__("nayvadius.reconciliation", fromlist=["_fingerprint"])._fingerprint(normalized)
            validation = validate_db_reconciliation_plan(normalized, root=root)

    candidates, skipped = [], list(plan.get("review", [])) + list(plan.get("skipped", []))
    for item in plan.get("auto", []):
        source = _safe_relative(root, item.get("source", ""))
        target = _safe_relative(root, item.get("target", ""))
        expected = item.get("hash", "")
        if source is None or target is None or source == target:
            skipped.append({"item": item, "reason": "invalid source or target"}); continue
        if not source.is_file():
            skipped.append({"item": item, "reason": "source is missing"}); continue
        if _contains_symlink(root, source):
            skipped.append({"item": item, "reason": "source path contains a symlink"}); continue
        if len(expected) != 64 or _sha256(source.read_bytes()) != expected:
            skipped.append({"item": item, "reason": "source changed since reconciliation plan"}); continue
        if _contains_symlink(root, target):
            skipped.append({"item": item, "reason": "target path contains a symlink"}); continue
        if target.exists() or target.is_symlink():
            skipped.append({"item": item, "reason": "target now exists or is a symlink"}); continue
        if target.suffix.lower() != ".md":
            skipped.append({"item": item, "reason": "target is not markdown"}); continue
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
    moved = []
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
            actual_hash = _sha256(data)
            if actual_hash != item["hash"]:
                raise RuntimeError(f"source changed during apply: {item['source']}")
            backup.write_bytes(data)
            manifest.append({"operation": "move", "original_path": source.relative_to(root).as_posix(),
                             "new_path": target.relative_to(root).as_posix(), "backup_path": backup.relative_to(root).as_posix(),
                             "original_hash": actual_hash})

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
            if _contains_symlink(root, source) or _contains_symlink(root, target):
                raise RuntimeError("source or target path contains a symlink during rename")
            if target.exists() or target.is_symlink():
                raise RuntimeError(f"target appeared during apply: {target.relative_to(root)}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if _contains_symlink(root, target.parent):
                raise RuntimeError("target parent contains a symlink during apply")
            source.rename(target)
            moved.append((source, target))

        manifest_path = backup_root / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"operations": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "APPLIED", "applied": [
            {"source": i["source"], "target": i["target"], "hash": i["hash"],
             "document_id": i.get("document_id"),
             "entity_resolution": i.get("entity_resolution"),
             "wikilink_resolution": i.get("wikilink_resolution")}
            for i, _, _ in candidates
        ], "skipped": skipped, "changed": len(candidates) + len(rewritten),
        "backup_manifest": manifest_path.relative_to(root).as_posix(), "validation": validation}
    except Exception as exc:
        rollback_errors = []
        for path, original in reversed(list(rewritten.items())):
            try:
                if _contains_symlink(root, path):
                    raise RuntimeError("rollback path contains a symlink")
                path.write_text(original, encoding="utf-8")
            except Exception as rollback_exc:
                rollback_errors.append(f"rewrite rollback failed for {path}: {rollback_exc}")
        for source, target in reversed(moved):
            try:
                if _contains_symlink(root, target) or _contains_symlink(root, source):
                    raise RuntimeError("rollback source or target contains a symlink")
                if target.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if _contains_symlink(root, source.parent):
                        raise RuntimeError("rollback source parent contains a symlink")
                    target.rename(source)
            except Exception as rollback_exc:
                rollback_errors.append(f"move rollback failed for {target}: {rollback_exc}")
        return {"status": "FAIL", "applied": [], "skipped": skipped, "changed": 0,
                "error": str(exc),
                "rollback": {"status": "FAILED" if rollback_errors else "RESTORED", "errors": rollback_errors},
                "validation": validation}


def verify_db_reconciliation_apply(root: str | Path, result: dict) -> dict:
    """Verify an applied reconciliation result without mutating the vault."""
    root = Path(root)
    if root.is_symlink() or not root.exists() or not root.is_dir():
        return {"status": "FAIL", "errors": ["vault root is missing, not a directory, or is a symlink"], "checked": 0}
    if not isinstance(result, dict):
        return {"status": "FAIL", "errors": ["apply result must be an object"], "checked": 0}
    if result.get("status") != "APPLIED":
        return {"status": "FAIL", "errors": ["apply result is not APPLIED"], "checked": 0}
    manifest_rel = result.get("backup_manifest")
    manifest_path = _safe_relative(root, manifest_rel or "")
    if manifest_path is None or not manifest_path.is_file():
        return {"status": "FAIL", "errors": ["backup manifest is missing"], "checked": 0}
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_hash = _sha256(manifest_bytes)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "errors": [f"invalid backup manifest: {exc}"], "checked": 0}
    if not isinstance(manifest, dict):
        return {"status": "FAIL", "errors": ["backup manifest must be an object"], "checked": 0, "manifest": manifest_rel}
    operations = manifest.get("operations")
    errors = []
    checked = 0
    if not isinstance(operations, list):
        return {"status": "FAIL", "errors": ["backup manifest operations must be a list"], "checked": 0, "manifest": manifest_rel}
    if not operations:
        return {"status": "FAIL", "errors": ["backup manifest contains no operations"], "checked": 0, "manifest": manifest_rel}

    move_keys = []
    rewrite_keys = []
    for operation in operations:
        if not isinstance(operation, dict):
            errors.append("manifest contains a non-object operation")
            continue
        kind = operation.get("operation")
        if kind == "move":
            original_path = operation.get("original_path")
            new_path = operation.get("new_path")
            backup_path = operation.get("backup_path")
            original_hash = operation.get("original_hash")
            if not isinstance(original_path, str) or not isinstance(new_path, str):
                errors.append("manifest move contains invalid path types")
                continue
            if not isinstance(backup_path, str):
                errors.append("manifest move contains invalid backup path")
                continue
            if not isinstance(original_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", original_hash):
                errors.append("manifest move contains invalid hash")
                continue
            move_keys.append((original_path, new_path, original_hash))
        elif kind == "wikilink_rewrite":
            path = operation.get("path")
            original_hash = operation.get("original_hash")
            new_hash = operation.get("new_hash")
            backup_path = operation.get("backup_path")
            if not isinstance(path, str):
                errors.append("manifest wikilink rewrite contains invalid path type")
                continue
            if not isinstance(original_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", original_hash):
                errors.append("manifest wikilink rewrite contains invalid original hash")
                continue
            if not isinstance(new_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", new_hash):
                errors.append("manifest wikilink rewrite contains invalid new hash")
                continue
            if not isinstance(backup_path, str):
                errors.append("manifest wikilink rewrite contains invalid backup path")
                continue
            rewrite_keys.append(path)
        else:
            errors.append(f"manifest contains unsupported operation: {kind!r}")

    if len(move_keys) != len(set(move_keys)):
        errors.append("manifest contains duplicate move operations")
    if len(rewrite_keys) != len(set(rewrite_keys)):
        errors.append("manifest contains duplicate wikilink rewrite operations")

    applied = result.get("applied")
    if not isinstance(applied, list):
        errors.append("apply result applied must be a list")
    elif not applied:
        errors.append("APPLIED result contains no applied entries")
    else:
        applied_keys = []
        for entry in applied:
            if not isinstance(entry, dict):
                errors.append("apply result contains a non-object applied entry")
                continue
            source = entry.get("source")
            target = entry.get("target")
            entry_hash = entry.get("hash")
            if not isinstance(source, str) or not isinstance(target, str) or not isinstance(entry_hash, str):
                errors.append("apply result contains invalid applied entry fields")
                continue
            if not re.fullmatch(r"[0-9a-fA-F]{64}", entry_hash):
                errors.append("apply result contains invalid applied entry hash")
                continue
            applied_keys.append((source, target, entry_hash))
        if Counter(applied_keys) != Counter(move_keys):
            errors.append("apply result applied entries do not match manifest move operations")
    for operation in operations:
        if not isinstance(operation, dict):
            errors.append("manifest contains a non-object operation")
            continue
        kind = operation.get("operation")
        if kind == "move":
            source = _safe_relative(root, operation.get("original_path", ""))
            target = _safe_relative(root, operation.get("new_path", ""))
            backup = _safe_relative(root, operation.get("backup_path", ""))
            original_hash = operation.get("original_hash")
            if not isinstance(original_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", original_hash):
                errors.append(f"move has invalid original hash: {operation.get('original_path')}")
                continue
            if (
                source is None
                or target is None
                or backup is None
                or _contains_symlink(root, source)
                or _contains_symlink(root, target)
                or _contains_symlink(root, backup)
                or not backup.is_file()
            ):
                errors.append("manifest contains an unsafe, symlinked, or missing move backup path")
                continue
            if _sha256(backup.read_bytes()) != original_hash:
                errors.append(f"move backup hash mismatch: {operation.get('original_path')}")
            if source.exists():
                errors.append(f"source still exists: {operation.get('original_path')}")
            if not target.is_file():
                errors.append(f"target is missing: {operation.get('new_path')}")
            elif _sha256(target.read_bytes()) != original_hash:
                errors.append(f"target hash mismatch: {operation.get('new_path')}")
            checked += 1
        elif kind == "wikilink_rewrite":
            new_hash = operation.get("new_hash")
            original_hash = operation.get("original_hash")
            backup_path = operation.get("backup_path")
            path = _safe_relative(root, operation.get("path", ""))
            backup = _safe_relative(root, backup_path or "")
            if (
                not isinstance(new_hash, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", new_hash)
                or not isinstance(original_hash, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", original_hash)
                or backup is None
                or _contains_symlink(root, backup)
                or not backup.is_file()
            ):
                errors.append(f"wikilink rewrite has invalid or missing backup metadata: {operation.get('path')}")
                continue
            if path is None or _contains_symlink(root, path) or not path.is_file():
                errors.append(f"rewritten file is missing: {operation.get('path')}")
            elif _sha256(path.read_bytes()) != new_hash:
                errors.append(f"rewritten file hash mismatch: {operation.get('path')}")
            if _sha256(backup.read_bytes()) != original_hash:
                errors.append(f"rewritten backup hash mismatch: {operation.get('path')}")
            checked += 1
    return {
        "status": "VERIFIED" if not errors else "FAIL",
        "errors": errors,
        "checked": checked,
        "manifest": manifest_rel,
        "manifest_hash": manifest_hash,
    }
