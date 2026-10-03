import json
from pathlib import Path
from .models import Document

def load_jsonl(path: str) -> list[Document]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("input file not found: " + path)
    docs = []
    seen = set()
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            x = json.loads(line)
            doc_id = str(x["id"])
            if doc_id in seen:
                raise ValueError("duplicate document id: " + doc_id)
            seen.add(doc_id)
            content = str(x["content"])
            if not content.strip():
                raise ValueError("empty content: " + doc_id)
            docs.append(Document(doc_id, str(x["title"]), content,
                                 str(x.get("source", "unknown")), x.get("metadata", {})))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid input line " + str(line_no) + ": " + str(exc)) from exc
    return docs
