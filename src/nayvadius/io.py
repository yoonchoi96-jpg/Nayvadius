import json
from pathlib import Path
from .models import Document

def load_jsonl(path: str) -> list[Document]:
    p = Path(path)
    if not p.exists():
        return []
    docs = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            x = json.loads(line)
            docs.append(Document(str(x["id"]), x["title"], x["content"], x.get("source","unknown"), x.get("metadata",{})))
    return docs
