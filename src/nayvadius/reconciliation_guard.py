from __future__ import annotations

from pathlib import Path
import re


from .reconciliation import _fingerprint


EXPECTED_PLAN_VERSION = 3
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PROTECTED_ROOTS = {"00_Inbox", "90_Dashboard", ".obsidian", ".nayvadius-backup"}
REQUIRED_TOP_LEVEL = {
    "title",
    "plan_version",
    "status",
    "previous_root",
    "current_root",
    "db_path",
    "auto",
    "review",
    "skipped",
    "diff",
    "db_summary",
    "summary",
    "fingerprint",
}


def validate_db_reconciliation_plan(plan: dict, root: str | Path | None = None) -> dict:
    """Validate a reconciliation plan before any future mutating consumer uses it.

    This is intentionally analysis-only. It rejects stale/tampered plans and
    malformed AUTO entries; it does not touch the vault or database.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(plan, dict):
        return {"status": "FAIL", "errors": ["plan must be an object"], "warnings": []}

    missing = sorted(REQUIRED_TOP_LEVEL - set(plan))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")

    if plan.get("plan_version") != EXPECTED_PLAN_VERSION:
        errors.append(f"unsupported plan_version: {plan.get('plan_version')!r}")

    if plan.get("status") not in {"PLANNED", "REVIEW", "CLEAN"}:
        errors.append(f"unsupported plan status: {plan.get('status')!r}")

    for field in ("title", "previous_root", "current_root", "db_path", "fingerprint"):
        if field in plan and not isinstance(plan[field], str):
            errors.append(f"{field} must be a string")

    if "fingerprint" in plan and (not isinstance(plan.get("fingerprint"), str) or not SHA256_RE.fullmatch(plan.get("fingerprint", ""))):
        errors.append("fingerprint is not a SHA-256 hex string")

    if "fingerprint" in plan:
        try:
            expected = _fingerprint(plan)
        except Exception as exc:
            errors.append(f"fingerprint calculation failed: {exc}")
        else:
            if plan.get("fingerprint") != expected:
                errors.append("fingerprint mismatch: plan may be stale or modified")

    for field in ("auto", "review", "skipped"):
        if field in plan and not isinstance(plan[field], list):
            errors.append(f"{field} must be a list")

    for field in ("review", "skipped"):
        for index, item in enumerate(plan.get(field, [])):
            if not isinstance(item, dict):
                errors.append(f"{field}[{index}] must be an object")

    for field in ("diff", "db_summary"):
        if field in plan and not isinstance(plan[field], dict):
            errors.append(f"{field} must be an object")

    for index, item in enumerate(plan.get("auto", [])):
        if not isinstance(item, dict):
            errors.append(f"auto[{index}] must be an object")
            continue
        if item.get("action") != "AUTO":
            errors.append(f"auto[{index}] is not marked AUTO")
        if item.get("kind") != "move":
            errors.append(f"auto[{index}] is not a move")
        for key in ("source", "target", "hash"):
            if not item.get(key):
                errors.append(f"auto[{index}] missing {key}")
        for key in ("source", "target"):
            if key in item and not isinstance(item.get(key), str):
                errors.append(f"auto[{index}] {key} must be a string")
        if item.get("source") == item.get("target"):
            errors.append(f"auto[{index}] source and target are identical")
        expected_hash = item.get("hash")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            errors.append(f"auto[{index}] hash is not a SHA-256 hex string")

        for label, value in (("source", item.get("source")), ("target", item.get("target"))):
            if isinstance(value, str):
                path = Path(value)
                if path.is_absolute() or not value or ".." in path.parts:
                    errors.append(f"auto[{index}] {label} is not a safe relative path")
                elif any(part in PROTECTED_ROOTS for part in path.parts):
                    errors.append(f"auto[{index}] {label} targets a protected path")
        target = item.get("target")
        if isinstance(target, str) and Path(target).suffix.lower() != ".md":
            errors.append(f"auto[{index}] target is not a markdown path")

        entity_resolution = item.get("entity_resolution")
        if entity_resolution is not None:
            if not isinstance(entity_resolution, dict):
                errors.append(f"auto[{index}] entity_resolution must be an object")
            elif entity_resolution.get("unresolved"):
                errors.append(f"auto[{index}] contains unresolved entity mappings")
        link_resolution = item.get("wikilink_resolution")
        if link_resolution is not None:
            if not isinstance(link_resolution, dict):
                errors.append(f"auto[{index}] wikilink_resolution must be an object")
            else:
                if link_resolution.get("unresolved"):
                    errors.append(f"auto[{index}] contains unresolved wikilinks")
                if link_resolution.get("status") == "unavailable":
                    warnings.append(f"auto[{index}] was planned without live wikilink verification")

    auto_keys = []
    for index, item in enumerate(plan.get("auto", [])):
        if not isinstance(item, dict):
            continue
        source, target, expected_hash = item.get("source"), item.get("target"), item.get("hash")
        if isinstance(source, str) and isinstance(target, str) and isinstance(expected_hash, str):
            auto_keys.append((source, target, expected_hash))
    if len(set(auto_keys)) != len(auto_keys):
        errors.append("auto contains duplicate reconciliation entries")

    summary = plan.get("summary", {})
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
    else:
        if summary.get("auto") != len(plan.get("auto", [])):
            errors.append("summary.auto does not match auto length")
        if summary.get("review") != len(plan.get("review", [])):
            errors.append("summary.review does not match review length")
        if summary.get("skipped") != len(plan.get("skipped", [])):
            errors.append("summary.skipped does not match skipped length")

    if "diff" in plan and isinstance(plan.get("diff"), dict):
        diff = plan["diff"]
        diff_summary = diff.get("summary")
        if isinstance(diff_summary, dict):
            if "changed" in diff_summary:
                if summary.get("changed") != diff_summary.get("changed"):
                    errors.append("summary.changed does not match diff.summary.changed")

            diff_keys = ("added", "deleted", "modified", "moved")
            diff_counts = {}
            for key in diff_keys:
                values = diff.get(key)
                if not isinstance(values, list):
                    errors.append(f"diff.{key} must be a list")
                else:
                    diff_counts[key] = len(values)

            if all(key in diff_counts for key in diff_keys):
                calculated_changed = sum(diff_counts.values())
                if diff_summary.get("changed") != calculated_changed:
                    errors.append("diff.summary.changed does not match diff item counts")
                for key in diff_keys:
                    if diff_summary.get(key) != diff_counts[key]:
                        errors.append(f"diff.summary.{key} does not match diff.{key} length")
        else:
            errors.append("diff.summary must be an object")

    auto_count = len(plan.get("auto", []))
    review_count = len(plan.get("review", []))
    if plan.get("status") == "CLEAN" and (auto_count or review_count):
        errors.append("CLEAN plan cannot contain AUTO or REVIEW entries")
    if plan.get("status") == "PLANNED" and auto_count == 0:
        errors.append("PLANNED plan must contain at least one AUTO entry")
    if plan.get("status") == "REVIEW" and review_count == 0:
        errors.append("REVIEW plan must contain at least one REVIEW entry")

    if root is not None:
        actual = Path(root).resolve()
        for key in ("previous_root", "current_root"):
            value = plan.get(key)
            if value and Path(value).resolve() != actual:
                errors.append(f"{key} does not match requested root")

    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "plan_version": plan.get("plan_version"),
        "auto": len(plan.get("auto", [])),
        "review": len(plan.get("review", [])),
        "skipped": len(plan.get("skipped", [])),
    }
