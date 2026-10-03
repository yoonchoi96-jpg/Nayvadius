import re
from .models import Document, Entity, Relation, ProcessedDocument

def process_document(doc: Document) -> ProcessedDocument:
    words = doc.content.split()
    names = []
    for n in re.findall(r"\b[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})*\b", doc.content):
        if n not in names:
            names.append(n)
    return ProcessedDocument(
        doc,
        " ".join(words[:120]),
        [Entity(n, "Concept", 0.5) for n in names[:30]],
        [f"source/{doc.source}"],
        [],
    )

def parse_llm(obj: dict, doc: Document) -> ProcessedDocument:
    def text(value, default=""):
        return value.strip() if isinstance(value, str) else default

    entities = []
    for raw in obj.get("entities", []) or []:
        if not isinstance(raw, dict):
            continue
        name = text(raw.get("name"))
        if not name:
            continue
        aliases = raw.get("aliases", []) or []
        entities.append(Entity(
            name=name,
            entity_type=text(raw.get("entity_type"), "Concept"),
            confidence=float(raw.get("confidence", 1.0)),
            aliases=tuple(str(x) for x in aliases),
        ))

    relations = []
    for raw in obj.get("relations", []) or []:
        if not isinstance(raw, dict):
            continue
        source = text(raw.get("source"))
        target = text(raw.get("target"))
        relation = text(raw.get("relation"))
        if source and target and relation:
            relations.append(Relation(
                source=source,
                relation=relation,
                target=target,
                confidence=float(raw.get("confidence", 1.0)),
            ))

    importance = float(obj.get("importance", 0.5))
    importance = max(0.0, min(1.0, importance))
    tags = [str(x) for x in (obj.get("tags", []) or []) if str(x).strip()]

    return ProcessedDocument(
        document=doc,
        summary=text(obj.get("summary"), doc.content[:500]),
        entities=entities,
        tags=tags or [f"source/{doc.source}"],
        related_ids=[str(x) for x in (obj.get("related_ids", []) or [])],
        relations=relations,
        importance=importance,
        document_type=text(obj.get("document_type"), "note"),
        translation_ko=text(obj.get("translation_ko")),
    )
