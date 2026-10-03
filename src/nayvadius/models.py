from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Document:
    id: str
    title: str
    content: str
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Entity:
    name: str
    entity_type: str
    confidence: float = 1.0

@dataclass(frozen=True)
class ProcessedDocument:
    document: Document
    summary: str
    entities: list[Entity]
    tags: list[str]
    related_ids: list[str]
