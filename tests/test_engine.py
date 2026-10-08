from nayvadius.models import Document, ProcessedDocument
from nayvadius.processor import process_document


def test_processor():
    r = process_document(Document("1", "Test", "Alice Smith wrote a note.", "test"))
    assert r.document.id == "1"
    assert r.tags == ["source/test"]


def test_processed_document_defaults_are_isolated():
    a = ProcessedDocument(Document("a", "A", "x"))
    b = ProcessedDocument(Document("b", "B", "y"))
    a.tags.append("source/a")
    assert b.tags == []
    a.entities.append("x")
    assert b.entities == []
