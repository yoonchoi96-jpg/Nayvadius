from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .obsidian_audit import _entity_files, _wikilink_matches, compare_vault_snapshots, normalize_entity_name, parse_wikilink, snapshot_vault


PLAN_VERSION = 3


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
        try:
            aliases = db.execute(
                "SELECT alias, canonical_name, entity_type FROM entity_aliases"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            aliases = []
        try:
            entity_rows = db.execute(
                "SELECT name, entity_type, aliases FROM entities"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            entity_rows = []

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

    alias_index = {}
    for alias, canonical_name, entity_type in aliases:
        key = (entity_type, normalize_entity_name(alias))
        alias_index.setdefault(key, set()).add(canonical_name)

    entity_alias_index = {}
    for name, entity_type, raw_aliases in entity_rows:
        try:
            parsed = json.loads(raw_aliases or "[]")
        except (TypeError, json.JSONDecodeError):
            parsed = []
        if isinstance(parsed, dict):
            parsed = list(parsed.keys())
        elif isinstance(parsed, str):
            parsed = [parsed]
        if not isinstance(parsed, list):
            parsed = []
        for alias in parsed:
            key = (entity_type, normalize_entity_name(alias))
            entity_alias_index.setdefault(key, set()).add(name)

    return {
        "by_hash": by_hash,
        "document_count": len(documents),
        "entity_links": len(entities),
        "aliases": {
            key: sorted(values)
            for key, values in alias_index.items()
        },
        "entity_aliases": {
            key: sorted(values)
            for key, values in entity_alias_index.items()
        },
    }



def _vault_entity_index(root):
    entities, _, _ = _entity_files(Path(root))
    index = {}
    for entity in entities:
        for value in [entity["name"], *entity["aliases"].values()]:
            index.setdefault((entity["domain"], normalize_entity_name(value)), []).append(entity)
    return index


def _vault_canonical_index(root):
    entities, _, _ = _entity_files(Path(root))
    index = {}
    for entity in entities:
        index.setdefault(
            (entity["domain"], normalize_entity_name(entity["name"])),
            [],
        ).append(entity)
    return index


def _resolve_db_entities(db_entities, vault_entities, db_aliases=None, canonical_vault_entities=None, db_entity_aliases=None):
    """Resolve DB entity references to one canonical Obsidian entity file.

    Resolution is intentionally conservative:
    exact canonical entity matches are preferred; an explicit DB
    entity_aliases mapping is then followed to the canonical DB name. Any
    missing, conflicting, or type-mismatched mapping remains REVIEW.
    """
    db_aliases = db_aliases or {}
    db_entity_aliases = db_entity_aliases or {}
    canonical_vault_entities = canonical_vault_entities or vault_entities
    resolved, unresolved = [], []

    for name, entity_type in db_entities:
        direct = {
            x["relative"]: x
            for x in canonical_vault_entities.get((entity_type, normalize_entity_name(name)), [])
        }
        if len(direct) == 1:
            entity = next(iter(direct.values()))
            resolved.append({
                "name": name,
                "entity_type": entity_type,
                "canonical_name": entity["name"],
                "file": entity["relative"],
                "resolution_method": "direct",
            })
            continue
        if len(direct) > 1:
            unresolved.append({
                "name": name,
                "entity_type": entity_type,
                "reason": "multiple canonical Obsidian entity files match",
                "files": sorted(direct),
            })
            continue

        explicit_targets = db_aliases.get((entity_type, normalize_entity_name(name)), [])
        entity_targets = db_entity_aliases.get((entity_type, normalize_entity_name(name)), [])
        explicit_set = set(explicit_targets)
        entity_set = set(entity_targets)
        alias_targets = sorted(explicit_set | entity_set)
        if len(alias_targets) != 1:
            unresolved.append({
                "name": name,
                "entity_type": entity_type,
                "reason": (
                    "conflicting DB entity alias mappings"
                    if len(alias_targets) > 1
                    else "no canonical Obsidian entity file or DB alias match"
                ),
                **({"canonical_names": sorted(alias_targets)} if alias_targets else {}),
            })
            continue

        canonical_name = alias_targets[0]
        alias_sources = []
        if canonical_name in explicit_set:
            alias_sources.append("entity_aliases")
        if canonical_name in entity_set:
            alias_sources.append("entities.aliases")
        candidates = {
            x["relative"]: x
            for x in vault_entities.get(
                (entity_type, normalize_entity_name(canonical_name)), []
            )
        }
        if len(candidates) == 1:
            entity = next(iter(candidates.values()))
            resolved.append({
                "name": name,
                "entity_type": entity_type,
                "canonical_name": entity["name"],
                "file": entity["relative"],
                "resolution_method": "db_alias",
                "db_alias": name,
                "alias_sources": alias_sources,
            })
        elif len(candidates) > 1:
            unresolved.append({
                "name": name,
                "entity_type": entity_type,
                "reason": "DB alias resolves to multiple canonical Obsidian entity files",
                "canonical_name": canonical_name,
                "files": sorted(candidates),
            })
        else:
            unresolved.append({
                "name": name,
                "entity_type": entity_type,
                "reason": "DB alias resolves to a canonical name absent from Obsidian",
                "canonical_name": canonical_name,
            })

    return {"resolved": resolved, "unresolved": unresolved}


def _wikilink_resolution(root, relative_path, vault_entities):
    path = Path(root) / relative_path
    if not path.exists() or path.suffix.lower() != ".md":
        return {"status": "unavailable", "links": [], "unresolved": [], "non_entity_links": []}
    links, unresolved, non_entity_links = [], [], []
    for match in _wikilink_matches(path.read_text(encoding="utf-8")):
        target = parse_wikilink(match.group(2))["target"]
        if not target or target.startswith(("http://", "https://")):
            continue
        candidates = {}
        for (domain, key), items in vault_entities.items():
            if key == normalize_entity_name(target):
                for item in items:
                    candidates[item["relative"]] = item
        if len(candidates) == 1:
            item = next(iter(candidates.values()))
            links.append({"target": target, "canonical_file": item["relative"], "entity_type": item["domain"]})
        elif len(candidates) > 1:
            unresolved.append(target)
        else:
            non_entity_links.append(target)
    return {"status": "checked", "links": links, "unresolved": sorted(set(unresolved)), "non_entity_links": sorted(set(non_entity_links))}

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


def build_db_reconciliation_plan(previous: dict, current: dict, db_path: str | Path, vault_root: str | Path | None = None) -> dict:
    """Cross-check vault changes against deterministic DB document identity."""
    diff = compare_vault_snapshots(previous, current)
    db_available = bool(db_path) and Path(db_path).exists()
    db_index = (
        _db_identity_index(db_path)
        if db_available
        else {"by_hash": {}, "document_count": 0, "entity_links": 0}
    )
    auto, review, skipped = [], [], []
    vault_entities = _vault_entity_index(vault_root) if vault_root else {}
    canonical_vault_entities = _vault_canonical_index(vault_root) if vault_root else {}

    for item in diff["moved"]:
        matches = _hash_matches(db_index, item["hash"])
        base = {"kind": "move", "source": item["from"], "target": item["to"], "hash": item["hash"]}
        if len(matches) == 1:
            entity_check = (
                _resolve_db_entities(
                    matches[0]["entities"],
                    vault_entities,
                    db_index["aliases"],
                    canonical_vault_entities,
                    db_index["entity_aliases"],
                )
                if vault_root
                else {"resolved": [], "unresolved": []}
            )
            link_check = _wikilink_resolution(vault_root, item["to"], vault_entities) if vault_root else {"status": "unavailable", "links": [], "unresolved": []}
            details = {"entity_resolution": entity_check, "wikilink_resolution": link_check}
            if vault_root and (entity_check["unresolved"] or link_check["unresolved"]):
                review.append({
                    "action": "REVIEW", **base, **_match_details(matches), **details,
                    "db_check": "DB identity matched but canonical entity/link resolution is incomplete",
                    "reason": "document identity is deterministic but Obsidian graph integrity is not proven",
                })
            else:
                auto.append({
                    "action": "AUTO", **base, **_match_details(matches), **details,
                    "db_check": "unique DB content_hash and canonical entity match",
                    "reason": "exact move with unique DB identity and resolved Obsidian graph",
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
            "explicit_aliases": sum(len(v) for v in db_index.get("aliases", {}).values()),
            "entity_metadata_aliases": sum(len(v) for v in db_index.get("entity_aliases", {}).values()),
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
    return current, build_db_reconciliation_plan(previous, current, db_path, vault_root=root)


def write_vault_snapshot(snapshot: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_db_reconciliation_plan(plan: dict, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
