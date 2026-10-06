from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .obsidian_audit import compare_vault_snapshots, snapshot_vault


PLAN_VERSION = 2


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
    by_id = {}
    for document_id, title, content_hash, source in documents:
        record = {
            "document_id": document_id,
            "title": title,
            "source": source,
            "entities": [],
        }
        by_hash.setdefault(content_hash, []).append(record)
        by_id[document_id] = record

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


def _hash_matches(db_index: dict, content_hash: str) -> list[dict]:
    return db_index["by_hash"].get(content_hash, [])


def _match_details(matches: list[dict]) -> dict:
    if len(matches) == 1:
        match = matches[0]
        return {
            "document_id": match["document_id"],
            "title": match["title"],
            "source": match["source"],
            "entities": match["entities"],
        }
    if len(matches) > 1:
        return {"document_ids": sorted(x["document_id"] for x in matches)}
    return {}


def build_db_reconciliation_plan(previous: dict, current: dict, db_path: str | Path) -> dict:
    """Cross-check vault changes against deterministic DB document identity."""
    diff = compare_vault_snapshots(previous, current)
    db_available = bool(db_path) and Path(db_path).exists()
    db_index = (
        _db_identity_index(db_path)
        if db_available
        else {"by_hash": {}, "document_count": 0, "entity_links": 0}
    )
    auto, review, skipped = [], [], []

    for item in diff["moved"]:
        matches = _hash_matches(db_index, item["hash"])
        base = {"kind": "move", "source": item["from"], "target": item["to"], "hash": item["hash"]}
        if len(matches) == 1:
            auto.append({
                "action": "AUTO", **base, **_match_details(matches),
                "db_check": "unique DB content_hash match",
                "reason": "exact content-preserving move with unique DB identity",
            })
        elif len(matches) > 1:
            review.append({
                "action": "REVIEW", **base, **_match_details(matches),
                "db_check": "ambiguous DB content_hash match",
                "reason": "multiple DB documents share the same content hash",
            })
        else:
            review.append({
                "action": "REVIEW", **base,
                "db_check": "no DB content_hash match",
                "reason": "vault move has no deterministic DB identity match",
            })

    for path in diff["added"]:
        matches = _hash_matches(db_index, current["files"][path]["hash"])
        item = {
            "action": "REVIEW", "kind": "added", "path": path,
            "hash": current["files"][path]["hash"],
            "reason": "new vault note requires reconciliation before DB linkage",
        }
        if len(matches) == 1:
            item.update(_match_details(matches))
            item["db_check"] = "hash matches existing DB document; path identity is new"
        elif len(matches) > 1:
            item.update(_match_details(matches))
            item["db_check"] = "hash matches multiple DB documents"
        else:
            item["db_check"] = "no DB content_hash match"
        review.append(item)

    for path in diff["deleted"]:
        matches = _hash_matches(db_index, previous["files"][path]["hash"])
        item = {
            "action": "REVIEW", "kind": "deleted", "path": path,
            "hash": previous["files"][path]["hash"],
            "reason": "deleted note may leave orphaned DB provenance",
        }
        if len(matches) == 1:
            item.update(_match_details(matches))
            item["db_check"] = "unique DB document may now be orphaned"
        elif len(matches) > 1:
            item.update(_match_details(matches))
            item["db_check"] = "multiple DB documents share deleted note hash"
        else:
            item["db_check"] = "no DB content_hash match"
        review.append(item)

    for path in diff["modified"]:
        before_matches = _hash_matches(db_index, previous["files"][path]["hash"])
        after_matches = _hash_matches(db_index, current["files"][path]["hash"])
        item = {
            "action": "REVIEW", "kind": "modified", "path": path,
            "before_hash": previous["files"][path]["hash"],
            "after_hash": current["files"][path]["hash"],
            "reason": "content changed; DB reconciliation requires semantic inspection",
        }
        if len(before_matches) == 1:
            item["document_id"] = before_matches[0]["document_id"]
            item["previous_db_entities"] = before_matches[0]["entities"]
            if len(after_matches) == 1 and after_matches[0]["document_id"] == before_matches[0]["document_id"]:
                item["db_check"] = "same DB document identity, but content is stale"
                item["identity_status"] = "stable"
            elif len(after_matches) > 1:
                item["db_check"] = "modified content matches multiple DB documents"
                item["identity_status"] = "ambiguous"
            elif len(after_matches) == 1:
                item["db_check"] = "modified content matches a different DB document"
                item["identity_status"] = "conflict"
            else:
                item["db_check"] = "same DB document identified by previous hash; new content not in DB"
                item["identity_status"] = "stale"
        else:
            item["db_check"] = (
                "previous content has no unique DB identity"
                if not before_matches else "previous content matches multiple DB documents"
            )
            item["identity_status"] = "unknown" if not before_matches else "ambiguous"
        review.append(item)

    if not db_available:
        skipped.append({"kind": "db", "reason": "DB unavailable; all changed items remain REVIEW"})

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
            "auto": len(auto), "review": len(review), "skipped": len(skipped),
            "changed": diff["summary"]["changed"],
        },
    }
    plan["fingerprint"] = _fingerprint(plan)
    return plan


def build_live_db_reconciliation_plan(previous: dict, root: str | Path, db_path: str | Path) -> tuple[dict, dict]:
    """Snapshot a live vault and reconcile it against a persisted previous snapshot."""
    current = snapshot_vault(root)
    return current, build_db_reconciliation_plan(previous, current, db_path)


def write_vault_snapshot(snapshot: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_db_reconciliation_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
