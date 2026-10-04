"""Deterministic second-stage QA for the Nayvadius knowledge graph.

This module intentionally performs zero LLM/API calls. It audits the persisted
SQLite state and returns machine-readable findings suitable for CI and later
selective AI review.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CANONICAL_TYPES = {
    "People", "Organizations", "Countries", "Places", "Products",
    "Technologies", "Concepts", "Events", "Institutions",
    "MusicTracks", "MusicAlbums",
}
VALID_EVIDENCE_STATUS = {"checked", "contradicted", "unverified"}
RELATION_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    context: dict[str, Any]


def _finding(rule, severity, message, **context):
    return Finding(rule, severity, message, context)


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def audit_database(path: str | Path) -> dict[str, Any]:
    """Audit the persisted Nayvadius DB without mutating it."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    findings: list[Finding] = []

    required = {
        "documents", "results", "entities", "document_entities", "relations",
        "document_relations", "evidence", "relation_evidence",
        "entity_aliases", "entity_sources", "entity_merge_log",
        "processing_failures", "vocabularies", "entity_vocabulary_links",
        "document_vocabulary_links", "vocabulary_sources",
    }
    missing = sorted(t for t in required if not _table_exists(db, t))
    if missing:
        findings.append(_finding(
            "schema.required_tables", "error",
            "Required tables are missing.", missing=missing,
        ))
        db.close()
        return _report(path, findings)

    # Entity ontology / duplicate / confidence checks.
    bad_types = db.execute(
        "SELECT name, entity_type FROM entities WHERE entity_type NOT IN ({}) "
        "ORDER BY entity_type,name".format(",".join("?" * len(CANONICAL_TYPES))),
        tuple(CANONICAL_TYPES),
    ).fetchall()
    for row in bad_types:
        findings.append(_finding(
            "entity.invalid_type", "error",
            "Entity uses a non-canonical entity type.",
            name=row["name"], entity_type=row["entity_type"],
        ))

    duplicate_names = db.execute(
        "SELECT name,entity_type,COUNT(*) AS n FROM entities "
        "GROUP BY name,entity_type HAVING COUNT(*) > 1"
    ).fetchall()
    for row in duplicate_names:
        findings.append(_finding(
            "entity.duplicate_pk", "error",
            "Duplicate canonical entity rows exist.",
            name=row["name"], entity_type=row["entity_type"], count=row["n"],
        ))

    bad_conf = db.execute(
        "SELECT name,entity_type,confidence FROM entities "
        "WHERE confidence < 0 OR confidence > 1 OR confidence IS NULL"
    ).fetchall()
    for row in bad_conf:
        findings.append(_finding(
            "entity.confidence_range", "error",
            "Entity confidence is outside [0,1].",
            name=row["name"], entity_type=row["entity_type"],
            confidence=row["confidence"],
        ))

    # Alias collisions are high-value semantic QA candidates. Do not auto-merge.
    alias_collisions = db.execute(
        "SELECT alias,entity_type,COUNT(DISTINCT canonical_name) AS n "
        "FROM entity_aliases GROUP BY alias,entity_type HAVING COUNT(DISTINCT canonical_name) > 1"
    ).fetchall()
    for row in alias_collisions:
        names = [r[0] for r in db.execute(
            "SELECT canonical_name FROM entity_aliases "
            "WHERE alias=? AND entity_type=? ORDER BY canonical_name",
            (row["alias"], row["entity_type"]),
        ).fetchall()]
        findings.append(_finding(
            "alias.ambiguous", "warning",
            "Alias maps to multiple canonical entities; review before merging.",
            alias=row["alias"], entity_type=row["entity_type"], canonical_names=names,
        ))

    orphan_aliases = db.execute(
        "SELECT ea.alias,ea.canonical_name,ea.entity_type FROM entity_aliases ea "
        "LEFT JOIN entities e ON e.name=ea.canonical_name AND e.entity_type=ea.entity_type "
        "WHERE e.name IS NULL LIMIT 100"
    ).fetchall()
    for row in orphan_aliases:
        findings.append(_finding(
            "alias.orphan", "error",
            "Alias points to a missing canonical entity.",
            alias=row["alias"], canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
        ))

    # Document/entity referential integrity.
    orphan_de = db.execute(
        "SELECT de.document_id,de.entity_name,de.entity_type FROM document_entities de "
        "LEFT JOIN documents d ON d.id=de.document_id "
        "LEFT JOIN entities e ON e.name=de.entity_name AND e.entity_type=de.entity_type "
        "WHERE d.id IS NULL OR e.name IS NULL LIMIT 100"
    ).fetchall()
    for row in orphan_de:
        findings.append(_finding(
            "document_entity.orphan", "error",
            "Document-entity link points to a missing document or entity.",
            document_id=row["document_id"], entity_name=row["entity_name"],
            entity_type=row["entity_type"],
        ))

    # Relation endpoints, naming, confidence, and self-loop checks.
    relations = db.execute(
        "SELECT source_name,relation,target_name,confidence FROM relations"
    ).fetchall()
    for row in relations:
        source = db.execute(
            "SELECT 1 FROM entities WHERE name=? LIMIT 1", (row["source_name"],)
        ).fetchone()
        target = db.execute(
            "SELECT 1 FROM entities WHERE name=? LIMIT 1", (row["target_name"],)
        ).fetchone()
        if not source or not target:
            findings.append(_finding(
                "relation.orphan_endpoint", "error",
                "Relation references a missing entity endpoint.",
                source=row["source_name"], relation=row["relation"],
                target=row["target_name"],
            ))
        if row["source_name"] == row["target_name"]:
            findings.append(_finding(
                "relation.self_loop", "warning",
                "Relation connects an entity to itself; review semantic validity.",
                source=row["source_name"], relation=row["relation"],
            ))
        if not RELATION_RE.fullmatch(row["relation"] or ""):
            findings.append(_finding(
                "relation.invalid_name", "error",
                "Relation type is not normalized snake_case.",
                relation=row["relation"],
            ))
        if row["confidence"] is None or not 0 <= float(row["confidence"]) <= 1:
            findings.append(_finding(
                "relation.confidence_range", "error",
                "Relation confidence is outside [0,1].",
                source=row["source_name"], relation=row["relation"],
                target=row["target_name"], confidence=row["confidence"],
            ))

    # Document relation links must point to existing documents and graph edges.
    orphan_dr = db.execute(
        "SELECT dr.document_id,dr.source_name,dr.relation,dr.target_name "
        "FROM document_relations dr LEFT JOIN documents d ON d.id=dr.document_id "
        "LEFT JOIN relations r ON r.source_name=dr.source_name AND r.relation=dr.relation "
        "AND r.target_name=dr.target_name WHERE d.id IS NULL OR r.source_name IS NULL LIMIT 100"
    ).fetchall()
    for row in orphan_dr:
        findings.append(_finding(
            "document_relation.orphan", "error",
            "Document-relation link points to a missing document or graph relation.",
            document_id=row["document_id"], source=row["source_name"],
            relation=row["relation"], target=row["target_name"],
        ))

    # Evidence links are provenance, so broken evidence is a hard QA failure.
    orphan_evidence = db.execute(
        "SELECT re.document_id,re.source_name,re.relation,re.target_name,re.evidence_document_id "
        "FROM relation_evidence re "
        "LEFT JOIN evidence e ON e.document_id=re.evidence_document_id "
        "WHERE e.document_id IS NULL LIMIT 100"
    ).fetchall()
    for row in orphan_evidence:
        findings.append(_finding(
            "relation_evidence.orphan", "error",
            "Relation evidence points to missing evidence.",
            document_id=row["document_id"], source=row["source_name"],
            relation=row["relation"], target=row["target_name"],
            evidence_document_id=row["evidence_document_id"],
        ))

    bad_status = db.execute(
        "SELECT document_id,source_name,relation,target_name,status "
        "FROM relation_evidence WHERE status NOT IN ({})".format(
            ",".join("?" * len(VALID_EVIDENCE_STATUS))
        ),
        tuple(VALID_EVIDENCE_STATUS),
    ).fetchall()
    for row in bad_status:
        findings.append(_finding(
            "relation_evidence.invalid_status", "error",
            "Relation evidence has an invalid status.",
            document_id=row["document_id"], source=row["source_name"],
            relation=row["relation"], target=row["target_name"],
            status=row["status"],
        ))

    # Results should not exist without a source document.
    orphan_results = db.execute(
        "SELECT r.document_id FROM results r LEFT JOIN documents d ON d.id=r.document_id "
        "WHERE d.id IS NULL LIMIT 100"
    ).fetchall()
    for row in orphan_results:
        findings.append(_finding(
            "result.orphan", "error",
            "Stored processing result has no source document.",
            document_id=row["document_id"],
        ))

    # Processing failures are not structural corruption, but are important QA signals.
    failure_count = db.execute(
        "SELECT COUNT(*) FROM processing_failures"
    ).fetchone()[0]
    if failure_count:
        findings.append(_finding(
            "processing.failures", "warning",
            "Processing failures are present and should be monitored.",
            count=failure_count,
        ))

    # Entity merge audit must never record a same-name merge.
    bad_merges = db.execute(
        "SELECT id,canonical_name,duplicate_name,entity_type FROM entity_merge_log "
        "WHERE canonical_name=duplicate_name"
    ).fetchall()
    for row in bad_merges:
        findings.append(_finding(
            "merge.invalid_self_merge", "error",
            "Entity merge log contains a self-merge.",
            id=row["id"], canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
        ))

    db.close()
    return _report(path, findings)


def _report(path: str | Path, findings: list[Finding]) -> dict[str, Any]:
    errors = [asdict(f) for f in findings if f.severity == "error"]
    warnings = [asdict(f) for f in findings if f.severity == "warning"]
    return {
        "schema_version": "1",
        "database": str(path),
        "status": "FAIL" if errors else "PASS",
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "total_findings": len(findings),
        },
        "findings": errors + warnings,
    }


def write_report(report: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
