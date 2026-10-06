from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .obsidian_audit import compare_vault_snapshots


PLAN_VERSION = 1


def _fingerprint(plan: dict) -> str:
    payload = {k: v for k, v in plan.items() if k != "fingerprint"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _db_identity_index(db_path: str | Path) -> dict:
    with sqlite3.connect(db_path) as db:
        documents = db.execute(
            "SELECT id, title, content_hash, source FROM documents"
        ).fetchall()
        entities = db.execute(
            "SELECT entity_name, entity_type, document_id FROM document_entities"
        ).fetchall()

    by_hash = {}
    for document_id, title, content_hash, source in documents:
        record = {
            "document_id": document_id,
            "title": title,
            "source": source,
            "entities": [],
        }
        by_hash.setdefault(content_hash, []).append(record)

    by_id = {
        record["document_id"]: record
        for records in by_hash.values()
        for record in records
    }
    for name, entity_type, document_id in entities:
        if document_id in by_id:
            by_id[document_id]["entities"].append((name, entity_type))
    for record in by_id.values():
        record["entities"].sort()

    return {
        "by_hash": by_hash,
        "document_count": len(documents),
        "entity_links": len(entities),
    }


def build_db_reconciliation_plan(
    previous: dict,
    current: dict,
    db_path: str | Path,
) -> dict:
    """Cross-check vault changes against deterministic DB document identity.

    No filesystem or database mutation occurs.
    """
    diff = compare_vault_snapshots(previous, current)
    db_available = bool(db_path) and Path(db_path).exists()
    db_index = (
        _db_identity_index(db_path)
        if db_available
        else {"by_hash": {}, "document_count": 0, "entity_links": 0}
    )
    auto, review, skipped = [], [], []

    for item in diff["moved"]:
        matches = db_index["by_hash"].get(item["hash"], [])
        base = {
            "kind": "move",
            "source": item["from"],
            "target": item["to"],
            "hash": item["hash"],
        }
        if len(matches) == 1:
            match = matches[0]
            auto.append({
                "action": "AUTO",
                **base,
                "document_id": match["document_id"],
                "title": match["title"],
                "source": match["source"],
                "entities": match["entities"],
                "db_check": "unique DB content_hash match",
                "reason": "exact content-preserving move with unique DB identity",
            })
        elif len(matches) > 1:
            review.append({
                "action": "REVIEW",
                **base,
                "document_ids": sorted(x["document_id"] for x in matches),
                "db_check": "ambiguous DB content_hash match",
                "reason": "multiple DB documents share the same content hash",
            })
        else:
            review.append({
                "action": "REVIEW",
                **base,
                "db_check": "no DB content_hash match",
                "reason": "vault move has no deterministic DB identity match",
            })

    for path in diff["added"]:
        review.append({
            "action": "REVIEW",
            "kind": "added",
            "path": path,
            "hash": current["files"][path]["hash"],
            "db_check": "new vault note has no prior path identity",
            "reason": "new note requires entity/document reconciliation",
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
            "reason": "content changed; semantic reconciliation required",
        })

    if not db_available:
        skipped.append({
            "kind": "db",
            "reason": "DB unavailable; vault-only classification retained",
        })

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
        "db_summary": {
            "documents": db_index["document_count"],
            "entity_links": db_index["entity_links"],
        },
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
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
