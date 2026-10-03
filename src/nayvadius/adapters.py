from abc import ABC, abstractmethod
import json

from .models import Document, Entity, Relation, ProcessedDocument
from .processor import normalize_entity_type


class DocumentAdapter(ABC):
    @abstractmethod
    def load(self) -> list[Document]:
        raise NotImplementedError


class JsonlAdapter(DocumentAdapter):
    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[Document]:
        from .io import load_jsonl
        return load_jsonl(self.path)


def _clean_list(value):
    return value if isinstance(value, list) else []


def _entity(raw):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    aliases = tuple(str(x).strip() for x in _clean_list(raw.get("aliases")) if str(x).strip())
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 1.0))))
    except (TypeError, ValueError):
        confidence = 1.0
    return Entity(name, normalize_entity_type(raw.get("entity_type")), confidence, aliases)


def _relation(raw):
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or "").strip()
    relation = str(raw.get("relation") or "").strip()
    target = str(raw.get("target") or "").strip()
    if not source or not relation or not target:
        return None
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 1.0))))
    except (TypeError, ValueError):
        confidence = 1.0
    return Relation(source, relation, target, confidence)


def parse_abraham_document(raw: dict) -> ProcessedDocument:
    if not isinstance(raw, dict):
        raise ValueError("Abraham record must be an object")
    doc_id = str(raw.get("id") or "").strip()
    content = str(raw.get("content") or "").strip()
    if not doc_id or not content:
        raise ValueError("Abraham record requires id and non-empty content")

    doc = Document(
        doc_id,
        str(raw.get("title") or doc_id),
        content,
        str(raw.get("source") or "abraham"),
        raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )
    entities = [x for x in (_entity(v) for v in _clean_list(raw.get("entities"))) if x]
    relations = [x for x in (_relation(v) for v in _clean_list(raw.get("relations"))) if x]
    tags = [str(x).strip() for x in _clean_list(raw.get("tags")) if str(x).strip()]
    related = [str(x).strip() for x in _clean_list(raw.get("related_ids")) if str(x).strip()]
    try:
        importance = max(0.0, min(1.0, float(raw.get("importance", 0.5))))
    except (TypeError, ValueError):
        importance = 0.5

    return ProcessedDocument(
        doc,
        str(raw.get("summary") or content[:500]),
        entities,
        tags or [f"source/{doc.source}"],
        related,
        relations,
        importance,
        str(raw.get("document_type") or "note"),
        str(raw.get("translation_ko") or ""),
    )


def load_abraham_jsonl(path: str) -> list[ProcessedDocument]:
    records = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(parse_abraham_document(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid Abraham input line {line_no}: {exc}") from exc
    return records


def load_documents(adapter: DocumentAdapter) -> list[Document]:
    return adapter.load()
