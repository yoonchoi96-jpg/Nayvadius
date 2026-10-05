from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .processor import ENTITY_TYPES

WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\r\n]+)\]\]")
LEGACY_ENTITY_TYPES = {"Companies": "Organizations", "Brands": "Organizations"}


def normalize_entity_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in value).split())


def parse_wikilink(value: str) -> dict[str, str | bool]:
    """Split an Obsidian target into destination, heading, and display text."""
    destination, separator, display = value.partition("|")
    target, anchor_separator, heading = destination.partition("#")
    return {
        "target": target.strip(),
        "heading": heading.strip() if anchor_separator else "",
        "display": display if separator else "",
        "has_display": bool(separator),
        "has_heading": bool(anchor_separator),
    }


def _format_wikilink(parsed: dict[str, str], target: str) -> str:
    value = target
    if parsed["has_heading"]:
        value += "#" + parsed["heading"]
    if parsed["has_display"]:
        value += "|" + parsed["display"]
    return value


def _wikilink_matches(text: str) -> list[re.Match]:
    """Find wikilinks outside Markdown fenced and inline code spans."""
    masked = bytearray(len(text))
    fence = None
    offset = 0
    fence_ranges = []
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if fence:
            marker, length = fence
            closing = re.match(r"^[ \t]{0,3}(" + re.escape(marker) + r"{"
                               + str(length) + r",})[ \t]*$", line.rstrip("\r\n"))
            if closing:
                fence_ranges.append((fence_start, line_end))
                fence = None
        else:
            opening = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
            if opening and not (
                opening.group(1).startswith("`") and "`" in opening.group(2)
            ):
                fence = (opening.group(1)[0], len(opening.group(1)))
                fence_start = offset
        offset = line_end
    if fence:
        fence_ranges.append((fence_start, len(text)))

    for start, end in fence_ranges:
        masked[start:end] = b"\1" * (end - start)

    runs = list(re.finditer(r"`+", text))
    open_runs = {}
    range_index = 0
    for run in runs:
        start, end = run.span()
        while range_index < len(fence_ranges) and start >= fence_ranges[range_index][1]:
            range_index += 1
        if masked[start]:
            continue
        backslashes = 0
        cursor = start - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            continue
        key = (range_index, end - start)
        opening = open_runs.pop(key, None)
        if opening:
            masked[opening[0]:end] = b"\1" * (end - opening[0])
        else:
            open_runs[key] = (start, end)

    return [
        match for match in WIKILINK_RE.finditer(text)
        if not match.group(1) and not any(masked[match.start():match.end()])
    ]


def _iter_markdown(root: str | Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*.md")
        if not path.is_symlink()
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], dict[str, str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, {}
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    aliases_value = fields.get("aliases", "")
    aliases = {}
    if aliases_value.startswith("[") and aliases_value.endswith("]"):
        for value in aliases_value[1:-1].split(","):
            alias = value.strip().strip("\"'")
            if alias:
                aliases[normalize_entity_name(alias)] = alias
    return fields, aliases


def _entity_files(root: Path) -> tuple[list[dict], list[str], list[dict]]:
    entity_root = root / "entities"
    entities, errors, warnings = [], [], []
    if not entity_root.exists():
        return entities, errors, warnings
    for path in _iter_markdown(entity_root):
        relative = path.relative_to(root)
        parts = relative.parts[1:]
        if not parts or path.name.startswith("_"):
            continue
        domain = parts[0]
        canonical_domain = LEGACY_ENTITY_TYPES.get(domain, domain)
        if canonical_domain not in ENTITY_TYPES:
            errors.append(f"legacy/unknown entity domain: {relative.as_posix()}")
            continue
        if len(parts) != 2:
            warnings.append({
                "kind": "unexpected_entity_path",
                "file": relative.as_posix(),
            })
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read entity note {relative.as_posix()}: {exc}")
            continue
        if not text.strip():
            errors.append(f"empty entity file: {relative.as_posix()}")
        if unicodedata.normalize("NFC", path.stem) != path.stem:
            warnings.append({
                "kind": "unicode_normalization",
                "file": relative.as_posix(),
                "normalized_name": unicodedata.normalize("NFC", path.stem),
            })
        fields, aliases = _parse_frontmatter(text)
        normalized = normalize_entity_name(path.stem)
        if not normalized:
            errors.append(f"entity filename contains no letters or digits: {relative.as_posix()}")
        frontmatter_name = fields.get("name")
        if frontmatter_name and frontmatter_name != path.stem:
            warnings.append({
                "kind": "frontmatter_name_mismatch",
                "file": relative.as_posix(),
                "filename": path.stem,
                "frontmatter_name": frontmatter_name,
            })
        if domain in LEGACY_ENTITY_TYPES:
            errors.append(f"legacy/unknown entity domain: {relative.as_posix()}")
            warnings.append({
                "kind": "legacy_entity_domain",
                "file": relative.as_posix(),
                "canonical_domain": canonical_domain,
            })
        entities.append({
            "name": path.stem,
            "domain": canonical_domain,
            "path": path,
            "relative": relative.as_posix(),
            "text": text,
            "fields": fields,
            "aliases": aliases,
            "normalized": normalized,
            "content_hash": _sha256(text),
        })
    return entities, errors, warnings


def _link_target_index(root: Path, files: list[Path], entities: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    entity_by_path = {item["path"]: item for item in entities}
    for path in files:
        record = entity_by_path.get(path)
        values = [path.stem]
        if record:
            values.extend(record["aliases"].values())
        relative = path.relative_to(root).with_suffix("").as_posix()
        values.append(relative)
        for value in values:
            key = normalize_entity_name(value)
            if key:
                index.setdefault(key, []).append({
                    "path": path,
                    "entity": record,
                    "relative": path.relative_to(root).as_posix(),
                })
    return index


def audit_vault(root: str | Path) -> dict:
    root = Path(root)
    errors: list[str] = []
    warnings: list[dict] = []
    if not root.exists():
        return {
            "status": "FAIL", "root": str(root), "files": 0, "entity_notes": 0,
            "errors": [f"vault root does not exist: {root}"], "warnings": [],
            "summary": {"scanned": 0, "clean": 0, "warning": 0, "error": 1},
        }

    files = _iter_markdown(root)
    entities, entity_errors, entity_warnings = _entity_files(root)
    errors.extend(entity_errors)
    warnings.extend(entity_warnings)
    index = _link_target_index(root, files, entities)
    incoming: set[Path] = set()

    groups: dict[tuple[str, str], list[dict]] = {}
    for entity in entities:
        if entity["normalized"]:
            groups.setdefault((entity["domain"], entity["normalized"]), []).append(entity)
    for (_, normalized), duplicates in sorted(groups.items()):
        if len(duplicates) < 2:
            continue
        names = sorted(item["relative"] for item in duplicates)
        kind = (
            "case_only_duplicate"
            if len({item["name"].casefold() for item in duplicates}) == 1
            else "duplicate_entity"
        )
        warnings.append({"kind": kind, "normalized_name": normalized, "files": names})

    alias_groups: dict[tuple[str, str], list[dict]] = {}
    for entity in entities:
        for alias, display in entity["aliases"].items():
            if alias and alias != entity["normalized"]:
                alias_groups.setdefault((entity["domain"], alias), []).append(entity)
    for (domain, alias), items in sorted(alias_groups.items()):
        unique = {item["normalized"]: item for item in items}
        if len(unique) > 1:
            warnings.append({
                "kind": "duplicate_entity_alias",
                "alias": alias,
                "entity_type": domain,
                "files": sorted(item["relative"] for item in unique.values()),
            })

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read Markdown file {path.relative_to(root).as_posix()}: {exc}")
            continue
        for match in _wikilink_matches(text):
            parsed = parse_wikilink(match.group(2))
            target = parsed["target"]
            if not target or target.startswith(("http://", "https://")):
                continue
            target_key = normalize_entity_name(target)
            target_parts = Path(target).parts
            candidates = index.get(target_key, [])
            if len(target_parts) >= 3 and target_parts[0] == "entities" and not candidates:
                candidates = index.get(normalize_entity_name(Path(target_parts[-1]).stem), [])
            source = path.resolve()
            unique_paths = sorted({item["path"] for item in candidates})
            expected_domain = None
            if len(target_parts) >= 3 and target_parts[0] == "entities":
                requested_domain = target_parts[1]
                expected_domain = LEGACY_ENTITY_TYPES.get(requested_domain, requested_domain)
                if expected_domain not in ENTITY_TYPES:
                    warnings.append({
                        "kind": "invalid_entity_domain_link",
                        "file": path.relative_to(root).as_posix(),
                        "target": target,
                        "domain": requested_domain,
                    })
                    continue
            if not unique_paths:
                warnings.append({
                    "kind": "unresolved_wikilink",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                    "heading": parsed["heading"],
                    "display": parsed["display"],
                })
                continue
            if len(unique_paths) > 1:
                warnings.append({
                    "kind": "ambiguous_wikilink",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                    "candidates": [candidate.relative_to(root).as_posix() for candidate in unique_paths],
                })
                continue
            destination = unique_paths[0]
            destination_record = next(
                (item["entity"] for item in candidates if item["path"] == destination),
                None,
            )
            if expected_domain and destination_record and destination_record["domain"] != expected_domain:
                warnings.append({
                    "kind": "wrong_entity_domain_link",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                    "expected_domain": expected_domain,
                    "actual_domain": destination_record["domain"],
                })
                continue
            if destination.resolve() == source:
                warnings.append({
                    "kind": "self_wikilink",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                })
            else:
                incoming.add(destination)
            if target != destination.stem and normalize_entity_name(target) == normalize_entity_name(destination.stem):
                warnings.append({
                    "kind": "noncanonical_wikilink",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                    "canonical_target": destination.stem,
                })
            if candidates[0]["entity"] and target_key in candidates[0]["entity"]["aliases"]:
                warnings.append({
                    "kind": "alias_wikilink",
                    "file": path.relative_to(root).as_posix(),
                    "target": target,
                    "canonical_target": destination.stem,
                })

    for entity in entities:
        if entity["path"] not in incoming:
            warnings.append({
                "kind": "orphan_entity",
                "file": entity["relative"],
                "name": entity["name"],
                "entity_type": entity["domain"],
            })

    warning_count = len(warnings)
    error_count = len(errors)
    return {
        "status": "FAIL" if error_count else "PASS",
        "root": str(root),
        "files": len(files),
        "entity_notes": len(entities),
        "entities": [{
            "name": entity["name"],
            "entity_type": entity["domain"],
            "file": entity["relative"],
            "aliases": list(entity["aliases"].values()),
        } for entity in entities],
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "scanned": len(files),
            "clean": max(0, len(files) - warning_count - error_count),
            "warning": warning_count,
            "review": sum(w.get("kind") in {"duplicate_entity", "case_only_duplicate", "ambiguous_wikilink"} for w in warnings),
            "error": error_count,
            "changed": 0,
            "skipped": 0,
        },
    }


def write_audit_report(report: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rewrite_target(text: str, replacements: dict[str, str]) -> tuple[str, int, list[dict]]:
    count = 0
    rewrites = []
    output = []
    offset = 0
    for match in _wikilink_matches(text):
        parsed = parse_wikilink(match.group(2))
        new_target = replacements.get(normalize_entity_name(parsed["target"]))
        if not new_target or new_target == parsed["target"]:
            continue
        count += 1
        formatted = _format_wikilink(parsed, new_target)
        rewrites.append({"from": match.group(2), "to": formatted})
        output.extend((text[offset:match.start()], match.group(1) + "[[" + formatted + "]]"))
        offset = match.end()
    if not count:
        return text, 0, rewrites
    output.append(text[offset:])
    return "".join(output), count, rewrites


def normalize_vault(root: str | Path, apply: bool = False) -> dict:
    """Plan canonical wikilink rewrites and apply them only with explicit consent."""
    root = Path(root)
    files = _iter_markdown(root)
    entities, _, _ = _entity_files(root)
    index = _link_target_index(root, files, entities)
    replacements: dict[str, str] = {}
    ambiguous: set[str] = set()
    for key, candidates in index.items():
        unique = {item["path"] for item in candidates}
        if len(unique) != 1:
            ambiguous.add(key)
            continue
        destination = next(iter(unique))
        record = next((item["entity"] for item in candidates if item["entity"]), None)
        replacements[key] = record["name"] if record else destination.stem

    changes = []
    planned_text: dict[Path, str] = {}
    for path in files:
        original = path.read_text(encoding="utf-8")
        updated, count, rewrites = _rewrite_target(original, replacements)
        if not count or updated == original:
            continue
        relative = path.relative_to(root).as_posix()
        changes.append({
            "file": relative, "count": count,
            "original_hash": _sha256(original), "new_hash": _sha256(updated),
            "rewrites": rewrites,
        })
        planned_text[path] = updated

    backup_root = root / ".nayvadius-backup"
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest = []
    if apply:
        for path, updated in planned_text.items():
            original = path.read_text(encoding="utf-8")
            backup = backup_root / "normalize" / operation / path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            temp = path.with_suffix(path.suffix + ".nayvadius.tmp")
            temp.write_text(updated, encoding="utf-8")
            temp.replace(path)
            manifest.append({
                "timestamp": operation, "operation": "normalize",
                "original_path": path.relative_to(root).as_posix(),
                "backup_path": backup.relative_to(root).as_posix(),
                "original_hash": _sha256(original), "new_hash": _sha256(updated),
            })
        if manifest:
            _append_backup_manifest(backup_root, manifest)

    return {
        "applied": apply,
        "changes": changes,
        "would_change": len(changes) if not apply else 0,
        "changed": len(changes) if apply else 0,
        "skipped": len(ambiguous),
        "summary": {
            "scanned": len(files), "clean": len(files) - len(changes),
            "warning": len(ambiguous), "review": len(ambiguous),
            "error": 0, "changed": len(changes) if apply else 0,
            "skipped": len(ambiguous),
        },
    }


def _frontmatter_signature(entity: dict) -> tuple:
    return tuple(sorted(
        (key, value) for key, value in entity["fields"].items()
        if key != "name"
    ))


def _candidate_item(domain: str, normalized: str, items: list[dict], action: str, reason: str) -> dict:
    files = sorted(items, key=lambda item: item["relative"])
    return {
        "domain": domain,
        "normalized_key": normalized,
        "candidates": [item["relative"] for item in files],
        "file_hashes": {item["relative"]: item["content_hash"] for item in files},
        "action": action,
        "classification": action,
        "reason": reason,
    }


def build_entity_merge_plan(root: str | Path) -> dict:
    """Classify duplicate candidates conservatively without changing the vault."""
    root = Path(root)
    entities, errors, warnings = _entity_files(root)
    groups: dict[tuple[str, str], list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for item in entities:
        if item["normalized"]:
            groups.setdefault((item["domain"], item["normalized"]), []).append(item)
            by_name.setdefault(item["normalized"], []).append(item)

    candidates = []
    for (domain, normalized), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        metadata = {_frontmatter_signature(item) for item in items}
        action = "AUTO" if len(metadata) == 1 else "REVIEW"
        reason = (
            "same entity domain and normalized name with no conflicting metadata"
            if action == "AUTO" else "duplicate names have conflicting frontmatter metadata"
        )
        candidates.append(_candidate_item(domain, normalized, items, action, reason))

    # Same normalized name across domains is deliberately never auto-merged.
    for normalized, items in sorted(by_name.items()):
        domains = {item["domain"] for item in items}
        if len(domains) > 1:
            candidates.append(_candidate_item(
                ",".join(sorted(domains)), normalized, items, "SKIP",
                "same normalized name occurs in different entity domains",
            ))

    alias_groups: dict[tuple[str, str], list[dict]] = {}
    for item in entities:
        for alias in item["aliases"]:
            if alias and alias != item["normalized"]:
                alias_groups.setdefault((item["domain"], alias), []).append(item)
    for (domain, alias), items in sorted(alias_groups.items()):
        if len({item["normalized"] for item in items}) > 1:
            candidates.append(_candidate_item(
                domain, alias, items, "SKIP",
                "alias resolves to multiple distinct canonical entities",
            ))

    name_index = {
        (item["domain"], item["normalized"]): item
        for item in entities if item["normalized"]
    }
    review_pairs = set()
    for item in entities:
        for alias in item["aliases"]:
            target = name_index.get((item["domain"], alias))
            if target and target["path"] != item["path"]:
                pair = tuple(sorted((item["relative"], target["relative"])))
                review_pairs.add(pair)
    for first, second in sorted(review_pairs):
        first_item = next(item for item in entities if item["relative"] == first)
        second_item = next(item for item in entities if item["relative"] == second)
        candidates.append(_candidate_item(
            first_item["domain"], first_item["normalized"],
            [first_item, second_item], "REVIEW",
            "an explicit alias points to another entity name; review before merging",
        ))

    candidates.sort(key=lambda item: (item["action"], item["domain"], item["normalized_key"]))
    actions = [item["action"] for item in candidates]
    status = "FAIL" if errors else ("REVIEW" if candidates else "CLEAN")
    return {
        "status": status,
        "candidate_count": len(candidates),
        "counts": {action: actions.count(action) for action in ("AUTO", "REVIEW", "SKIP")},
        "candidates": candidates,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "scanned": len(entities), "clean": max(0, len(entities) - len(candidates)),
            "warning": len(warnings), "review": actions.count("REVIEW"),
            "error": len(errors), "changed": 0, "skipped": actions.count("SKIP"),
        },
    }


def write_merge_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_plan_path(root: Path, relative: str) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    lexical = root / candidate
    if any((root / Path(*candidate.parts[:index])).is_symlink()
           for index in range(1, len(candidate.parts) + 1)):
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to((root / "entities").resolve())
    except ValueError:
        return None
    if not lexical.is_file() or not resolved.is_file():
        return None
    return resolved


def _append_backup_manifest(backup_root: Path, entries: list[dict]) -> None:
    path = backup_root / "manifest.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"operations": []}
    existing.setdefault("operations", []).extend(entries)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def apply_entity_merge_plan(
    root: str | Path,
    plan: dict,
    backup_dir: str = ".nayvadius-backup",
    apply: bool = False,
) -> dict:
    """Plan or apply only AUTO candidates, backing up notes and rewrites first."""
    root = Path(root)
    would_merge, applied, skipped = [], [], []
    for item in plan.get("candidates", []):
        if not isinstance(item, dict):
            skipped.append({"item": item, "reason": "candidate is invalid"})
            continue
        paths = item.get("candidates", [])
        if item.get("action") != "AUTO":
            skipped.append({"item": item, "reason": "REVIEW and SKIP candidates require human handling"})
            continue
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            skipped.append({"item": item, "reason": "candidate paths are invalid"})
            continue
        if len(paths) < 2 or len(set(paths)) != len(paths):
            skipped.append({"item": item, "reason": "candidate paths are duplicate or incomplete"})
            continue
        resolved = [_safe_plan_path(root, value) for value in paths]
        if any(path is None for path in resolved) or len(set(resolved)) != len(resolved):
            skipped.append({"item": item, "reason": "candidate path is invalid or missing"})
            continue
        expected = item.get("file_hashes", {})
        if not isinstance(expected, dict) or not expected or any(
            _sha256(path.read_bytes()) != expected.get(relative)
            for relative, path in zip(paths, resolved)
        ):
            skipped.append({"item": item, "reason": "candidate files changed since planning"})
            continue
        ordered = sorted(
            zip(paths, resolved),
            key=lambda pair: (
                pair[1].stem != pair[1].stem.title(),
                pair[1].stem != " ".join(pair[1].stem.split()),
                pair[0],
            ),
        )
        canonical_rel, canonical = ordered[0]
        for duplicate_rel, duplicate in ordered[1:]:
            would_merge.append({
                "canonical": canonical_rel,
                "merged": duplicate_rel,
                "rewrite_target": canonical.stem,
            })

    replacements: dict[str, str] = {}
    merge_rows = []
    for merge in would_merge:
        duplicate = Path(merge["merged"])
        replacements[normalize_entity_name(duplicate.stem)] = merge["rewrite_target"]
        merge_rows.append(merge)

    rewritten: dict[Path, tuple[str, str, list[dict]]] = {}
    duplicate_paths = {merge["merged"] for merge in merge_rows}
    for path in _iter_markdown(root):
        relative = path.relative_to(root).as_posix()
        if relative in duplicate_paths:
            continue
        original = path.read_text(encoding="utf-8")
        updated, count, links = _rewrite_target(original, replacements)
        if count and updated != original:
            rewritten[path] = (original, updated, links)

    rewrite_plan = [
        {
            "file": path.relative_to(root).as_posix(),
            "original_hash": _sha256(original),
            "new_hash": _sha256(updated),
            "rewrites": links,
        }
        for path, (original, updated, links) in rewritten.items()
    ]
    if not apply:
        return {
            "status": "PLANNED" if would_merge else ("REVIEW" if skipped else "CLEAN"),
            "applied": [], "would_merge": would_merge, "rewrites": rewrite_plan,
            "skipped": skipped, "changed": 0,
            "summary": {"scanned": len(plan.get("candidates", [])),
                        "clean": 0, "warning": 0, "review": len(skipped),
                        "error": 0, "changed": 0, "skipped": len(skipped)},
        }

    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = root / backup_dir
    destinations = [backup_root / merge["merged"] for merge in merge_rows]
    destinations.extend(
        backup_root / "rewrites" / operation / path.relative_to(root)
        for path in rewritten
    )
    if any(path.exists() for path in destinations):
        return {
            "status": "FAIL", "applied": [],
            "would_merge": would_merge,
            "skipped": skipped + [{"reason": "backup destination already exists; no files changed"}],
            "changed": 0,
        }

    manifest = []
    try:
        for merge in merge_rows:
            original = root / merge["merged"]
            backup = backup_root / merge["merged"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, backup)
            manifest.append({
                "timestamp": operation, "operation": "entity_merge",
                "original_path": merge["merged"], "new_path": None,
                "backup_path": backup.relative_to(root).as_posix(),
                "original_hash": _sha256(original.read_bytes()),
                "new_hash": None,
            })
        for path, (original, updated, _) in rewritten.items():
            backup = backup_root / "rewrites" / operation / path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            manifest.append({
                "timestamp": operation, "operation": "wikilink_rewrite",
                "original_path": path.relative_to(root).as_posix(),
                "new_path": path.relative_to(root).as_posix(),
                "backup_path": backup.relative_to(root).as_posix(),
                "original_hash": _sha256(original), "new_hash": _sha256(updated),
            })
        for path, (_, updated, _) in rewritten.items():
            temp = path.with_suffix(path.suffix + ".nayvadius.tmp")
            temp.write_text(updated, encoding="utf-8")
            temp.replace(path)
        for merge in merge_rows:
            (root / merge["merged"]).unlink()
        if manifest:
            _append_backup_manifest(backup_root, manifest)
    except Exception:
        for path, (original, _, _) in rewritten.items():
            path.write_text(original, encoding="utf-8")
        for merge in merge_rows:
            backup = backup_root / merge["merged"]
            if backup.exists() and not (root / merge["merged"]).exists():
                shutil.copy2(backup, root / merge["merged"])
        raise

    applied.extend(merge_rows)
    return {
        "status": "APPLIED" if applied else ("REVIEW" if skipped else "CLEAN"),
        "applied": applied,
        "would_merge": would_merge,
        "rewrites": rewrite_plan,
        "skipped": skipped,
        "changed": len(applied) + len(rewritten),
        "backup_manifest": (backup_root / "manifest.json").relative_to(root).as_posix() if manifest else None,
        "summary": {
            "scanned": len(plan.get("candidates", [])),
            "clean": 0, "warning": 0, "review": len(skipped),
            "error": 0, "changed": len(applied) + len(rewritten),
            "skipped": len(skipped),
        },
    }


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def audit_vault_database(root: str | Path, db_path: str | Path) -> dict:
    """Compare Obsidian entity notes and links with a read-only SQLite snapshot."""
    root, db_path = Path(root), Path(db_path)
    audit = audit_vault(root)
    vault_entities, _, _ = _entity_files(root)
    obsidian_by_key: dict[tuple[str, str], dict] = {}
    for entity in vault_entities:
        obsidian_by_key[(entity["domain"], entity["normalized"])] = entity

    db_entities = {}
    db_relations = []
    db_missing_relation_entities = []
    document_entities_missing_entities = []
    document_entities_missing_documents = []
    entity_sources_missing_entities = []
    entity_sources_missing_documents = []
    provenance = set()
    errors = []
    if not db_path.exists():
        errors.append(f"database does not exist: {db_path}")
    else:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        has_entities = _table_exists(db, "entities")
        has_documents = _table_exists(db, "documents")
        if has_entities:
            for row in db.execute("SELECT name,entity_type,aliases FROM entities"):
                domain = LEGACY_ENTITY_TYPES.get(row["entity_type"], row["entity_type"])
                db_entities[(domain, normalize_entity_name(row["name"]))] = {
                    "name": row["name"], "entity_type": domain,
                    "aliases": [value.strip() for value in (row["aliases"] or "").split(",") if value.strip()],
                }
        if _table_exists(db, "entity_sources"):
            provenance = {
                (row["entity_name"], row["entity_type"])
                for row in db.execute("SELECT DISTINCT entity_name,entity_type FROM entity_sources")
            }
            source_columns = {row["name"] for row in db.execute("PRAGMA table_info(entity_sources)")}
            source_fields = "entity_name,entity_type"
            if "document_id" in source_columns:
                source_fields += ",document_id"
            for row in db.execute(f"SELECT {source_fields} FROM entity_sources"):
                entity_key = (
                    LEGACY_ENTITY_TYPES.get(row["entity_type"], row["entity_type"]),
                    normalize_entity_name(row["entity_name"]),
                )
                if entity_key not in db_entities:
                    entity_sources_missing_entities.append({
                        "entity_name": row["entity_name"],
                        "entity_type": entity_key[0],
                    })
                if "document_id" in source_columns and has_documents and not db.execute(
                    "SELECT 1 FROM documents WHERE id=? LIMIT 1", (row["document_id"],)
                ).fetchone():
                    entity_sources_missing_documents.append({
                        "entity_name": row["entity_name"],
                        "entity_type": entity_key[0],
                        "document_id": row["document_id"],
                    })
        if _table_exists(db, "document_entities"):
            document_entity_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(document_entities)")
            }
            if {"document_id", "entity_name", "entity_type"} <= document_entity_columns:
                for row in db.execute(
                    "SELECT document_id,entity_name,entity_type FROM document_entities"
                ):
                    domain = LEGACY_ENTITY_TYPES.get(row["entity_type"], row["entity_type"])
                    entity_key = (domain, normalize_entity_name(row["entity_name"]))
                    if entity_key not in db_entities:
                        document_entities_missing_entities.append({
                            "document_id": row["document_id"],
                            "entity_name": row["entity_name"],
                            "entity_type": domain,
                        })
                    if has_documents and not db.execute(
                        "SELECT 1 FROM documents WHERE id=? LIMIT 1", (row["document_id"],)
                    ).fetchone():
                        document_entities_missing_documents.append({
                            "document_id": row["document_id"],
                            "entity_name": row["entity_name"],
                            "entity_type": domain,
                        })
        if _table_exists(db, "relations"):
            db_relations = [
                (row["source_name"], row["relation"], row["target_name"])
                for row in db.execute("SELECT source_name,relation,target_name FROM relations")
            ]
            for source, relation, target in db_relations:
                missing = []
                for name in (source, target):
                    if not has_entities or not db.execute(
                        "SELECT 1 FROM entities WHERE name=? LIMIT 1", (name,)
                    ).fetchone():
                        missing.append(name)
                if missing:
                    db_missing_relation_entities.append({
                        "source": source, "relation": relation, "target": target,
                        "missing_entities": sorted(set(missing)),
                    })
        db.close()

    obsidian_only = []
    no_provenance = []
    for key, entity in obsidian_by_key.items():
        db_entity = db_entities.get(key)
        if not db_entity:
            obsidian_only.append({"name": entity["name"], "entity_type": entity["domain"], "file": entity["relative"]})
        elif (db_entity["name"], db_entity["entity_type"]) not in provenance:
            no_provenance.append({"name": db_entity["name"], "entity_type": db_entity["entity_type"], "file": entity["relative"]})
    db_only = [
        {**entity, "file": None}
        for key, entity in db_entities.items() if key not in obsidian_by_key
    ]

    links_absent_db = []
    if db_path.exists():
        files = _iter_markdown(root)
        index = _link_target_index(root, files, vault_entities)
        for source_path in files:
            for match in _wikilink_matches(source_path.read_text(encoding="utf-8")):
                target_name = parse_wikilink(match.group(2))["target"]
                key = normalize_entity_name(target_name)
                candidates = index.get(key, [])
                candidate_paths = {item["path"] for item in candidates}
                if len(candidate_paths) == 1:
                    entity = candidates[0]["entity"]
                    if entity and (entity["domain"], entity["normalized"]) not in db_entities:
                        links_absent_db.append({
                            "file": source_path.relative_to(root).as_posix(),
                            "target": target_name,
                            "entity_type": entity["domain"],
                        })

    relation_missing = []
    vault_keys = set(obsidian_by_key)
    for source, relation, target in db_relations:
        missing = []
        for name in (source, target):
            if not any(norm == normalize_entity_name(name) for _, norm in vault_keys):
                missing.append(name)
        if missing:
            relation_missing.append({
                "source": source, "relation": relation, "target": target,
                "missing_entities": sorted(set(missing)),
            })
    return {
        "database": str(db_path),
        "obsidian_only": obsidian_only,
        "obsidian_without_db_provenance": no_provenance,
        "links_to_entities_absent_from_db": links_absent_db,
        "db_only": db_only,
        "db_entities_missing_canonical_files": [
            entity for entity in db_only if entity.get("aliases")
        ],
        "document_entities_missing_db_entities": document_entities_missing_entities,
        "document_entities_missing_documents": document_entities_missing_documents,
        "entity_sources_missing_db_entities": entity_sources_missing_entities,
        "entity_sources_missing_documents": entity_sources_missing_documents,
        "db_relations_missing_db_endpoints": db_missing_relation_entities,
        "db_relations_missing_vault_endpoints": relation_missing,
        "errors": errors,
        "summary": {
            "obsidian_only": len(obsidian_only),
            "obsidian_without_db_provenance": len(no_provenance),
            "links_to_entities_absent_from_db": len(links_absent_db),
            "db_only": len(db_only),
            "db_entities_missing_canonical_files": sum(bool(entity.get("aliases")) for entity in db_only),
            "document_entities_missing_db_entities": len(document_entities_missing_entities),
            "document_entities_missing_documents": len(document_entities_missing_documents),
            "entity_sources_missing_db_entities": len(entity_sources_missing_entities),
            "entity_sources_missing_documents": len(entity_sources_missing_documents),
            "db_relations_missing_db_endpoints": len(db_missing_relation_entities),
            "db_relations_missing_vault_endpoints": len(relation_missing),
            "error": len(errors),
        },
    }


def maintenance_report(root: str | Path, db_path: str | Path) -> dict:
    audit = audit_vault(root)
    merge_plan = build_entity_merge_plan(root)
    consistency = audit_vault_database(root, db_path)
    consistency_issues = sum(
        count for key, count in consistency["summary"].items() if key != "error"
    )
    summary = {
        "scanned": audit["summary"]["scanned"],
        "clean": audit["summary"]["clean"],
        "warning": audit["summary"]["warning"],
        "review": merge_plan["counts"]["REVIEW"] + audit["summary"]["review"] + consistency_issues,
        "error": audit["summary"]["error"] + consistency["summary"]["error"],
        "db_consistency_issues": consistency_issues,
        "changed": 0,
        "skipped": merge_plan["counts"]["SKIP"],
        "unresolved_links": sum(w["kind"] == "unresolved_wikilink" for w in audit["warnings"]),
        "entities_scanned": audit["entity_notes"],
        "duplicate_entities": sum(w["kind"] in {"duplicate_entity", "case_only_duplicate"} for w in audit["warnings"]),
        "orphan_entities": sum(w["kind"] == "orphan_entity" for w in audit["warnings"]),
        "db_only_entities": consistency["summary"]["db_only"],
        "obsidian_only_entities": consistency["summary"]["obsidian_only"],
        "auto_merge_candidates": merge_plan["counts"]["AUTO"],
        "review_merge_candidates": merge_plan["counts"]["REVIEW"],
        "skip_merge_candidates": merge_plan["counts"]["SKIP"],
    }
    status = "FAIL" if summary["error"] else (
        "REVIEW" if summary["warning"] or summary["review"] or summary["skipped"] else "PASS"
    )
    return {
        "title": "Nayvadius Maintenance Report",
        "status": status,
        "summary": summary,
        "obsidian_audit": audit,
        "db_consistency": consistency,
        "merge_plan": merge_plan,
    }


def write_maintenance_report(report: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
