from nayvadius.hash import content_hash
from nayvadius.models import Document
from nayvadius.processor import process_document


def test_hash():
    assert content_hash("x") == content_hash("x")


def test_process_document():
    result = process_document(Document("1", "T", "Apple works with Google.", "test"))
    assert result.document.title == "T"
    assert result.tags == ["source/test"]
    assert any(e.name == "Apple" for e in result.entities)
