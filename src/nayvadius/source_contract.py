from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceIdentity:
    source: str
    source_id: str
    metadata: dict[str, Any]


def build_source_identity(document) -> SourceIdentity | None:
    """Return the canonical external identity carried by a document.

    Every ingested record has one stable pair: (source, source_id).
    source_id is taken from metadata first, then the document id as the
    deterministic fallback. The original metadata is preserved.
    """
    source = str(getattr(document, "source", "") or "").strip().casefold()
    metadata = dict(getattr(document, "metadata", {}) or {})
    source_id = str(
        metadata.get("source_id")
        or metadata.get("external_id")
        or getattr(document, "id", "")
        or ""
    ).strip()
    if not source or not source_id:
        return None
    metadata["source"] = source
    metadata["source_id"] = source_id
    return SourceIdentity(source, source_id, metadata)


def validate_source_identity(document) -> SourceIdentity:
    identity = build_source_identity(document)
    if identity is None:
        raise ValueError("document requires non-empty source and source_id")
    return identity
