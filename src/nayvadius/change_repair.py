from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .obsidian_audit import compare_vault_snapshots, snapshot_vault

PLAN_VERSION = 1


def _fingerprint(plan: dict) -> str:
    payload = {k: v for k, v in plan.items() if k != "fingerprint"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_change_repair_plan(previous: dict, current: dict) -> dict:
    """Turn deterministic vault changes into a conservative repair proposal.

    No filesystem or database mutation occurs here. Only exact content-preserving
    moves are AUTO; additions, deletions, and content modifications require REVIEW.
    """
    diff = compare_vault_snapshots(previous, current)
    auto = []
    review = []
    skipped = []

    for item in diff["moved"]:
        auto.append({
            "action": "AUTO",
            "kind": "move",
            "source": item["from"],
            "target": item["to"],
            "hash": item["hash"],
            "reason": "exact content-preserving path move",
        })

    for path in diff["added"]:
        review.append({
            "action": "REVIEW",
            "kind": "added",
            "path": path,
            "hash": current["files"][path]["hash"],
            "reason": "new note has no prior identity",
        })

    for path in diff["deleted"]:
        review.append({
            "action": "REVIEW",
            "kind": "deleted",
            "path": path,
            "hash": previous["files"][path]["hash"],
            "reason": "note disappeared without a recoverable matching destination",
        })

    for path in diff["modified"]:
        review.append({
            "action": "REVIEW",
            "kind": "modified",
            "path": path,
            "before_hash": previous["files"][path]["hash"],
            "after_hash": current["files"][path]["hash"],
            "reason": "content changed and requires semantic review",
        })

    plan = {
        "title": "Nayvadius Change Repair Plan",
        "plan_version": PLAN_VERSION,
        "status": "REVIEW" if review else ("PLANNED" if auto else "CLEAN"),
        "previous_root": previous.get("root"),
        "current_root": current.get("root"),
        "auto": auto,
        "review": review,
        "skipped": skipped,
        "diff": diff,
        "summary": {
            "auto": len(auto),
            "review": len(review),
            "skipped": len(skipped),
            "changed": diff["summary"]["changed"],
        },
    }
    plan["fingerprint"] = _fingerprint(plan)
    return plan


def write_change_repair_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_live_change_repair_plan(root: str | Path, previous: dict) -> dict:
    """Snapshot a vault and build a repair plan against a supplied prior snapshot."""
    current = snapshot_vault(root)
    return build_change_repair_plan(previous, current)
