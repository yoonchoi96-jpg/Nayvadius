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


def _contains_symlink_component(path: Path) -> bool:
    """Reject a path whose existing components include symlinks."""
    current = Path(path.anchor) if path.is_absolute() else Path()
    parts = path.parts
    if path.is_absolute():
        parts = parts[1:]
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def finalize_db_reconciliation_provenance(
    db_path: str | Path,
    vault_root: str | Path,
    apply_result: dict,
    verification: dict,
    *,
    apply: bool = False,
) -> dict:
    if not isinstance(apply_result, dict):
        return {"status": "REVIEW", "recorded": 0, "reason": "apply result must be an object"}
    if not isinstance(verification, dict):
        return {"status": "REVIEW", "recorded": 0, "reason": "verification result must be an object"}
    if apply_result.get("status") != "APPLIED":
        return {"status": "REVIEW", "recorded": 0, "reason": "apply result is not APPLIED"}
    if verification.get("status") != "VERIFIED":
        return {"status": "REVIEW", "recorded": 0, "reason": "apply result is not VERIFIED"}
    if apply_result.get("skipped"):
        return {"status": "REVIEW", "recorded": 0, "reason": "pending reconciliation items remain"}

    entries = apply_result.get("applied", [])
    if not isinstance(entries, list):
        return {"status": "FAIL", "recorded": 0, "reason": "invalid applied entries"}

    vault_root = Path(vault_root)
    if vault_root.is_symlink() or not vault_root.exists() or not vault_root.is_dir():
        return {"status": "REVIEW", "recorded": 0, "reason": "vault root is missing, not a directory, or is a symlink"}
    manifest_rel = apply_result.get("backup_manifest", "")
    if not isinstance(manifest_rel, str):
        return {"status": "REVIEW", "recorded": 0, "reason": "backup manifest path must be a string"}
    manifest_path = _safe_relative(vault_root, manifest_rel)
    if manifest_path is None or not manifest_path.is_file():
        return {"status": "REVIEW", "recorded": 0, "reason": "backup manifest is missing or unsafe"}
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_hash = __import__("hashlib").sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "REVIEW", "recorded": 0, "reason": f"invalid backup manifest: {exc}"}
    operations = manifest.get("operations") if isinstance(manifest, dict) else None
    if not isinstance(operations, list):
        return {"status": "REVIEW", "recorded": 0, "reason": "invalid backup manifest structure"}
    move_keys = set()
    move_count = 0
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            return {"status": "REVIEW", "recorded": 0, "reason": f"manifest operation {index} must be an object"}
        kind = op.get("operation")
        if kind == "move":
            move_count += 1
            original_path = op.get("original_path")
            new_path = op.get("new_path")
            original_hash = op.get("original_hash")
            backup_path = op.get("backup_path")
            if not isinstance(original_path, str) or not isinstance(new_path, str):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest move {index} has invalid path types"}
            if apply and not isinstance(backup_path, str):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest move {index} has invalid backup path"}
            if not isinstance(backup_path, str):
                backup_path = "" 
            if (
                _safe_relative(vault_root, original_path) is None
                or _safe_relative(vault_root, new_path) is None
                or (apply and _safe_relative(vault_root, backup_path) is None)
            ):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest move {index} has unsafe path"}
            if not isinstance(original_hash, str) or not SHA256_RE.fullmatch(original_hash):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest move {index} has invalid hash"}
            move_keys.add((original_path, new_path, original_hash))
        elif kind == "wikilink_rewrite":
            path = op.get("path")
            original_hash = op.get("original_hash")
            new_hash = op.get("new_hash")
            backup_path = op.get("backup_path")
            if not isinstance(path, str) or not isinstance(backup_path, str):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest rewrite {index} has invalid path types"}
            if _safe_relative(vault_root, path) is None or _safe_relative(vault_root, backup_path) is None:
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest rewrite {index} has unsafe path"}
            if not isinstance(original_hash, str) or not SHA256_RE.fullmatch(original_hash):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest rewrite {index} has invalid original hash"}
            if not isinstance(new_hash, str) or not SHA256_RE.fullmatch(new_hash):
                return {"status": "REVIEW", "recorded": 0, "reason": f"manifest rewrite {index} has invalid new hash"}
        else:
            return {"status": "REVIEW", "recorded": 0, "reason": f"unsupported manifest operation: {kind!r}"}
    if len(move_keys) != move_count:
        return {"status": "REVIEW", "recorded": 0, "reason": "manifest contains duplicate move operations"}

    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid applied entry"}
        document_id = entry.get("document_id")
        old_path = entry.get("source")
        new_path = entry.get("target")
        content_hash = entry.get("hash")
        if not isinstance(old_path, str) or not isinstance(new_path, str):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid applied path types", "entry": entry}
        if not isinstance(content_hash, str):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid content hash type", "entry": entry}
        if not document_id:
            return {"status": "REVIEW", "recorded": 0, "reason": "AUTO entry lacks document_id", "entry": entry}
        if not SHA256_RE.fullmatch(content_hash):
            return {"status": "FAIL", "recorded": 0, "reason": "invalid content hash", "entry": entry}
        if (old_path, new_path, content_hash) not in move_keys:
            return {"status": "REVIEW", "recorded": 0, "reason": "applied entry is absent from manifest", "entry": entry}
        validated.append((str(document_id), old_path, new_path, content_hash))

    if not apply:
        return {"status": "PLANNED", "recorded": len(validated), "entries": entries, "manifest": manifest_rel}

    from .db_reconciliation_apply import verify_db_reconciliation_apply
    live_verification = verify_db_reconciliation_apply(vault_root, apply_result)
    if live_verification.get("status") != "VERIFIED":
        return {
            "status": "REVIEW",
            "recorded": 0,
            "reason": "live reconciliation verification failed",
            "verification": live_verification,
        }
    db_path = Path(db_path)
    if _contains_symlink_component(db_path):
        return {"status": "REVIEW", "recorded": 0, "reason": "database path contains a symlink"}
    if not db_path.is_file():
        return {"status": "FAIL", "recorded": 0, "reason": "database is missing"}

    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=30)
    except (OSError, sqlite3.Error) as exc:
        return {"status": "REVIEW", "recorded": 0, "reason": f"database could not be opened: {exc}"}
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
        recorded = 0
        already_recorded = 0
        for entry in validated:
            document_id, old_path, new_path, content_hash = entry
            row = conn.execute("SELECT content_hash FROM documents WHERE id = ?", (document_id,)).fetchone()
            if row is None or str(row[0] or "") != content_hash:
                conn.rollback()
                return {"status": "REVIEW", "recorded": 0, "reason": "DB document identity mismatch", "document_id": document_id}
            cursor = conn.execute(
                """INSERT OR IGNORE INTO reconciliation_provenance
                   (document_id, content_hash, old_path, new_path, manifest_path, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    content_hash,
                    old_path,
                    new_path,
                    str(apply_result.get("backup_manifest", "")),
                    now,
                ),
            )
            if cursor.rowcount == 1:
                recorded += 1
            else:
                already_recorded += 1
        conn.commit()
        return {
            "status": "FINALIZED",
            "recorded": recorded,
            "already_recorded": already_recorded,
            "verified_at": now,
        }
    except Exception as exc:
        conn.rollback()
        return {"status": "FAIL", "recorded": 0, "reason": str(exc)}
    finally:
        conn.close()
