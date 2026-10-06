from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path

from .obsidian_audit import compare_vault_snapshots


PLAN_VERSION = 1


def _fingerprint(plan: dict) -> str:
    payload = {k: v for k, v in plan.items() if k != "fingerprint"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _db_entity_paths(db_path: str | Path) -> dict[tuple[str, str], set[str]]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT entity_name, entity_type, document_id FROM document_entities"
        ).fetchall()
    result = {}
    for name, entity_type, document_id in rows:
        result.setdefault((name, entity_type), set()).add(document_id)
    return result


def build_db_reconciliation_plan(
    previous: dict,
    current: dict,
    db_path: str | Path,
) -> dict:
    """Cross-check deterministic vault changes against DB identity/provenance.

    This is analysis-only. It never mutates the vault or database.
    """
    diff = compare_vault_snapshots(previous, current)
    db_entities = _db_entity_paths(db_path) if Path(db_path).exists() else {}
    auto, review, skipped = [], [], []

    for item in diff["moved"]:
        source = item["from"]
        target = item["to"]
        auto.append({
            "action": "AUTO",
            "kind": "move",
            "source": source,
            "target": target,
            "hash": item["hash"],
            "db_check": "content identity preserved; DB identity does not require mutation",
            "reason": "exact content-preserving move",
        })

    for path in diff["added"]:
        review.append({
            "action": "REVIEW",
            "kind": "added",
            "path": path,
            "hash": current["files"][path]["hash"],
            "db_check": "no prior path identity",
            "reason": "new vault note requires entity/document reconciliation",
        })

    for path in diff["deleted"]:
        review.append({
            "action": "REVIEW",
            "kind": "deleted",
            "path": path,
            "hash": previous["files"][path]["hash"],
            "db_check": "possible orphaned DB provenance",
            "reason": "deleted note may leave DB records requiring review",
        })

    for path in diff["modified"]:
        review.append({
            "action": "REVIEW",
            "kind": "modified",
            "path": path,
            "before_hash": previous["files"][path]["hash"],
            "after_hash": current["files"][path]["hash"],
            "db_check": "document/entity provenance may be stale",
            "reason": "content changed; DB reconciliation requires semantic inspection",
        })

    # Keep this explicit even though it is currently only diagnostic: callers can
    # use it to detect whether the DB has entity records at all.
    db_entity_count = len(db_entities)
    if not db_path or not Path(db_path).exists():
        skipped.append({
            "kind": "db",
            "reason": "DB unavailable; vault-only classification retained",
        })
        db_entity_count = 0

    plan = {
        "title": "Nayvadius DB ↔ Vault Reconciliation Plan",
        "plan_version": PLAN_VERSION,
        "status": "REVIEW" if review else ("PLANNED" if auto else "CLEAN"),
        "previous_root": previous.get("root"),
        "current_root": current.get("root"),
        "db_path": str(db_path),
        "auto": auto,
        "review": review,
        "skipped": skipped,
        "diff": diff,
        "db_summary": {"entity_identities": db_entity_count},
        "summary": {
            "auto": len(auto),
            "review": len(review),
            "skipped": len(skipped),
            "changed": diff["summary"]["changed"],
        },
    }
    plan["fingerprint"] = _fingerprint(plan)
    return plan


def write_db_reconciliation_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
