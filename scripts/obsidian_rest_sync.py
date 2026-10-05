#!/usr/bin/env python3
"""Bridge Nayvadius to the live Obsidian vault through Local REST API.

The bridge mirrors Markdown notes into a temporary directory, runs the existing
read-only/audit/merge engines, then applies only the resulting file changes back
through the Obsidian REST API. Every remote overwrite/delete is backed up first,
and writes are aborted if a note changed after the mirror was created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from nayvadius.db import connect, merge_entity
from nayvadius.obsidian_audit import (
    audit_vault,
    build_entity_merge_plan,
    apply_entity_merge_plan,
    maintenance_report,
    normalize_vault,
)


DEFAULT_URL = "https://127.0.0.1:27124"
DEFAULT_VAULT = "/Users/w/Desktop/Invest/Invest Insight"


class ObsidianREST:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.ctx = ssl._create_unverified_context()

    def request(self, method: str, path: str, body: bytes | None = None,
                content_type: str | None = None, accept: str | None = None) -> bytes:
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        url = f"{self.base}/vault/{encoded}" if path else f"{self.base}/vault/"
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Obsidian REST {method} {path}: HTTP {exc.code}: {detail[:500]}") from exc

    def list_dir(self, path: str = "") -> list[str]:
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/") if part)
        url = f"{self.base}/vault/{encoded}/" if encoded else f"{self.base}/vault/"
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        with urllib.request.urlopen(req, context=self.ctx, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("files", [])

    def read(self, path: str) -> bytes:
        return self.request("GET", path)

    def write(self, path: str, content: bytes) -> None:
        self.request("PUT", path, content, "text/markdown")

    def delete(self, path: str) -> None:
        self.request("DELETE", path)

    def copy_remote(self, source: str, destination: str) -> None:
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in source.split("/"))
        url = f"{self.base}/vault/{encoded}"
        req = urllib.request.Request(
            url,
            headers={**self.headers, "Destination": destination},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=60):
                pass
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Obsidian REST copy {source}: HTTP {exc.code}: {detail[:500]}") from exc


def api_key_from(vault: Path) -> str:
    explicit = os.environ.get("OBSIDIAN_API_KEY")
    if explicit:
        return explicit
    candidates = [
        vault / ".obsidian/plugins/obsidian-local-rest-api/data.json",
        vault / ".obsidian/plugins/local-rest-api-ng/data.json",
    ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("apiKey"):
                return str(data["apiKey"])
    raise RuntimeError("OBSIDIAN_API_KEY is not set and no Local REST API data.json was found")


def mirror(api: ObsidianREST, root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def walk(directory: str) -> None:
        for item in api.list_dir(directory):
            relative = f"{directory}/{item}" if directory else item
            parts = [p for p in relative.split("/") if p]
            if any(p.startswith(".") for p in parts):
                continue
            if item.endswith("/"):
                walk(relative.rstrip("/"))
                continue
            if not relative.lower().endswith(".md"):
                continue
            data = api.read(relative)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[relative] = hashlib.sha256(data).hexdigest()

    walk("")
    return files


def snapshot_local(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
    }


def remote_backup(api: ObsidianREST, source: str, backup_root: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = f"{backup_root}/{stamp}/{source}"
    api.copy_remote(source, destination)
    return destination


def apply_remote_changes(api: ObsidianREST, before: dict[str, bytes],
                          after: dict[str, bytes], backup_root: str) -> list[dict]:
    changed = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        current = api.read(path) if old is not None else None
        if old is not None and current != old:
            raise RuntimeError(
                f"ABORT: remote note changed during reconciliation: {path}"
            )
        backup = remote_backup(api, path, backup_root) if old is not None else None
        if new is None:
            api.delete(path)
            operation = "delete"
        else:
            api.write(path, new)
            operation = "write"
        changed.append({"path": path, "operation": operation, "backup": backup})
    return changed


def run(args: argparse.Namespace) -> dict:
    vault = Path(args.vault).expanduser().resolve()
    api = ObsidianREST(args.url, api_key_from(vault))
    # Authenticated connectivity check; this also fails fast before touching temp state.
    api.list_dir("")

    db_path = Path(args.db)
    with tempfile.TemporaryDirectory(prefix="nayvadius-obsidian-") as temp:
        mirror_root = Path(temp) / "vault"
        before_hashes = mirror(api, mirror_root)
        before = snapshot_local(mirror_root)

        initial_audit = audit_vault(mirror_root)

        # Normalize links first. This is deterministic and preserves heading/display
        # components. It only changes canonicalizable links.
        normalization = normalize_vault(mirror_root, apply=True)

        plan = build_entity_merge_plan(mirror_root)
        merge_result = apply_entity_merge_plan(mirror_root, plan, apply=True)

        db_merges = []
        for item in merge_result.get("applied", []):
            canonical = Path(item["canonical"]).stem
            duplicate = Path(item["merged"]).stem
            parts = Path(item["canonical"]).parts
            entity_type = parts[1] if len(parts) > 1 else ""
            if entity_type:
                merged = merge_entity(
                    canonical, duplicate, entity_type,
                    reason="exact_name", db_path=db_path,
                )
                db_merges.append({
                    "canonical": canonical,
                    "duplicate": duplicate,
                    "entity_type": entity_type,
                    "merged": merged,
                })

        after = snapshot_local(mirror_root)
        backup_root = args.backup_root.rstrip("/")
        remote_changes = apply_remote_changes(api, before, after, backup_root)

        # Re-mirror after writes so the final report describes the actual vault state.
        final_root = Path(temp) / "final"
        final_hashes = mirror(api, final_root)
        final_audit = audit_vault(final_root)
        final_maintenance = maintenance_report(final_root, db_path)

        return {
            "status": final_maintenance["status"],
            "vault": str(vault),
            "endpoint": args.url,
            "initial_markdown_files": len(before_hashes),
            "final_markdown_files": len(final_hashes),
            "normalization": {
                "changed": normalization.get("changed", 0),
                "changes": len(normalization.get("changes", [])),
            },
            "merge_plan": plan.get("counts", {}),
            "merge_apply": {
                "status": merge_result.get("status"),
                "changed": merge_result.get("changed", 0),
            },
            "db_merges": db_merges,
            "remote_changes": remote_changes,
            "initial_audit_status": initial_audit.get("status"),
            "final_audit_status": final_audit.get("status"),
            "maintenance": final_maintenance,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=os.environ.get("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT))
    parser.add_argument("--db", default="data/nayvadius.db")
    parser.add_argument("--url", default=os.environ.get("OBSIDIAN_REST_URL", DEFAULT_URL))
    parser.add_argument("--backup-root", default=".nayvadius-backup/live-rest")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    Path("output").mkdir(exist_ok=True)
    Path("output/obsidian_live_sync_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
