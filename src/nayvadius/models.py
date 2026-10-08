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
    entity_type: str = "Concept"
    confidence: float = 1.0
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Relation:
    source: str
    relation: str
    target: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Vocabulary:
    id: str
    word: str
    traditional: str = ""
    pinyin: str = ""
    pos: str = ""
    meaning_ko: str = ""
    hsk_levels: tuple[str, ...] = ()
    wordbooks: tuple[str, ...] = ()
    source: str = "abel"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessedDocument:
    document: Document
    summary: str
    entities: list[Entity]
    tags: list[str]
    related_ids: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    importance: float = 0.5
    document_type: str = "note"
    translation_ko: str = ""
