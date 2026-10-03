from pathlib import Path
from .models import ProcessedDocument

def write_markdown(result: ProcessedDocument, root: str) -> Path:
    p = Path(root)
    p.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in result.document.title).strip()[:120]
    out = p / f"{safe or result.document.id}.md"
    entities = "\n".join(f"- [[{e.name}]] ({e.entity_type})" for e in result.entities)
    tags = " ".join("#" + t.replace("/","-") for t in result.tags)
    out.write_text(f"# {result.document.title}\n\n{tags}\n\n## Summary\n{result.summary}\n\n## Entities\n{entities}\n", encoding="utf-8")
    return out
