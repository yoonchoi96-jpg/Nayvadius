import json
from pathlib import Path

from nayvadius.adapters import load_abraham_jsonl


def test_load_abraham_jsonl_preserves_enrichment(tmp_path: Path):
    p = tmp_path / "abraham.jsonl"
    p.write_text(json.dumps({
        "id": "rw-1",
        "title": "Example",
        "content": "Original",
        "source": "readwise",
        "metadata": {"readwise_id": "rw-1"},
        "tags": ["topic/test"],
        "translation_ko": "원문",
        "entities": [
            {"name": "Apple", "entity_type": "company", "confidence": 0.9}
        ],
        "relations": [
            {"source": "Apple", "relation": "related_to", "target": "Example"}
        ],
    }) + "
", encoding="utf-8")

    records = load_abraham_jsonl(str(p))
    result = records[0]

    assert result.document.id == "rw-1"
    assert result.entities[0].entity_type == "Companies"
    assert result.relations[0].source == "Apple"
    assert result.translation_ko == "원문"
    assert result.document.metadata["readwise_id"] == "rw-1"
