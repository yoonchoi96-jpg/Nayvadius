import re
from .models import Document, Entity, ProcessedDocument

def process_document(doc: Document) -> ProcessedDocument:
    words=doc.content.split()
    names=[]
    for n in re.findall(r"\\b[A-Z][A-Za-z]{2,}(?:\\s+[A-Z][A-Za-z]{2,})*\\b",doc.content):
        if n not in names: names.append(n)
    return ProcessedDocument(doc," ".join(words[:120]),[Entity(n,"Concept",0.5) for n in names[:30]],[f"source/{doc.source}"],[])
