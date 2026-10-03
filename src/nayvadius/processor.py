import re
from .models import Document, Entity, ProcessedDocument

NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")

def process_document(doc: Document) -> ProcessedDocument:
    words = doc.content.split()
    entities = []
    seen = set()
    for match in NAME.finditer(doc.content):
        key = match.group(0)
        if key not in seen:
            seen.add(key)
            entities.append(Entity(key, "people", 0.35))
    tags = [f"source/{doc.source}"]
    if len(words) > 500:
        tags.append("long-form")
    return ProcessedDocument(doc, " ".join(words[:80]), entities, tags, [])
