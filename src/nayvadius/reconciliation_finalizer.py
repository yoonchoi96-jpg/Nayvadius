"""Finalize verified DB↔Vault reconciliation provenance.

This module is deliberately separate from Vault mutation: it records only
reconciliation facts after a successful, independently verified apply.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

def _safe_relative(root: Path, value: str) -> Path | None:
    candidate = Path(str(value or ""))
    if candidate.is_absolute() or not value or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def finalize_db_reconciliation_provenance(
    db_path: str | Path,
    vault_root: str | Path,
    apply_result: dict,
    verification: dict,
    *,
    apply: bool = False,
) -> dict:
    if apply_result.get("status") != "APPLIED":
        return {"status": "REVIEW", "recorded": 0, "reason": "apply result is not APPLIED"}
    if verification.get("status") != "VERIFIED":
        return {"status": "REVIEW", "recorded": 0, "reason": "apply result is not VERIFIED"}

    entries = apply_result.get("applied", [])
    if not isinstance(entries, list):
        return {"status": "FAIL", "recorded": 0, "reason": "invalid applied entries"}

    vault_root = Path(vault_root)
    manifest_rel = str(apply_result.get("backup_manifest", ""))
    manifest_path = _safe_relative(vault_root, manifest_rel)
    if manifest_path is None or not manifest_path.is_file():
        return {"status": "REVIEW", "recorded": 0, "reason": "backup manifest is missing or unsafe"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "REVIEW", "recorded": 0, "reason": f"invalid backup manifest: {exc}"}
    operations = manifest.get("operations") if isinstance(manifest, dict) else None
    if not isinstance(operations, list):
        return {"status": "REVIEW", "recorded": 0, "reason": "invalid backup manifest structure"}
    move_keys = {
        (op.get("original_path"), op.get("new_path"), op.get("original_hash"))
        for op in operations
        if isinstance(op, dict) and op.get("operation") == "move"
    }

    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid applied entry"}
        document_id = entry.get("document_id")
        old_path = str(entry.get("source", ""))
        new_path = str(entry.get("target", ""))
        content_hash = str(entry.get("hash", ""))
        if not document_id:
            return {"status": "REVIEW", "recorded": 0, "reason": "AUTO entry lacks document_id", "entry": entry}
        if not SHA256_RE.fullmatch(content_hash):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid content hash", "entry": entry}
        if (old_path, new_path, content_hash) not in move_keys:
            return {"status": "REVIEW", "recorded": 0, "reason": "applied entry is absent from manifest", "entry": entry}
        validated.append((str(document_id), old_path, new_path, content_hash))

    if not apply:
        return {"status": "PLANNED", "recorded": len(validated), "entries": entries, "manifest": manifest_rel}

    db_path = Path(db_path)
    if not db_path.is_file():
        return {"status": "FAIL", "recorded": 0, "reason": "database is missing"}

    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reconciliation_provenance (
                document_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                old_path TEXT NOT NULL,
                new_path TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                PRIMARY KEY(document_id, content_hash, old_path, new_path)
            )"""
        )
        for entry in entries:
            document_id = entry.get("document_id")
            if not document_id:
                conn.rollback()
                return {
                    "status": "REVIEW",
                    "recorded": 0,
                    "reason": "AUTO entry lacks document_id",
                    "entry": entry,
                }
            old_path = str(entry.get("source", ""))
            new_path = str(entry.get("target", ""))
            content_hash = str(entry.get("hash", ""))
            if len(content_hash) != 64:
                conn.rollback()
                return {"status": "FAIL", "recorded": 0, "reason": "invalid content hash"}
            conn.execute(
                """INSERT OR IGNORE INTO reconciliation_provenance
                   (document_id, content_hash, old_path, new_path, manifest_path, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(document_id),
                    content_hash,
                    old_path,
                    new_path,
                    str(apply_result.get("backup_manifest", "")),
                    now,
                ),
            )
        conn.commit()
        return {"status": "FINALIZED", "recorded": len(entries), "verified_at": now}
    except Exception as exc:
        conn.rollback()
        return {"status": "FAIL", "recorded": 0, "reason": str(exc)}
    finally:
        conn.close()
