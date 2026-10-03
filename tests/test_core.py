import json
from pathlib import Path
from nayvadius.hash import content_hash
from nayvadius.models import Document
from nayvadius.processor import process_document, parse_llm
from nayvadius.io import load_jsonl

def test_hash():
    assert content_hash("x") == content_hash("x")

def test_process_document():
    result = process_document(Document("1", "T", "Apple works with Google.", "test"))
    assert result.document.title == "T"
    assert any(e.name == "Apple" for e in result.entities)

def test_parse_llm():
    result = parse_llm({
        "summary": "A summary",
        "importance": 0.8,
        "tags": ["a"],
        "entities": [{"name": "Ada Lovelace", "entity_type": "People", "confidence": 0.9}],
        "relations": [{"source": "Ada Lovelace", "relation": "worked_on", "target": "Analytical Engine"}],
        "translation_ko": "요약",
    }, Document("1", "T", "x"))
    assert result.importance == 0.8
    assert result.entities[0].name == "Ada Lovelace"
    assert result.relations[0].target == "Analytical Engine"

def test_input_validation(tmp_path: Path):
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"id":"a","title":"A","content":"x"}) + "\n" +
                 json.dumps({"id":"a","title":"B","content":"y"}) + "\n", encoding="utf-8")
    try:
        load_jsonl(str(p))
    except ValueError:
        return
    assert False


def test_parse_llm_rejects_non_object():
    try:
        parse_llm([], Document("1", "T", "x"))
    except ValueError:
        return
    assert False
