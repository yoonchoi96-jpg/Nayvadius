from nayvadius.models import Document
from nayvadius.processor import process_document

def test_processor():
    r = process_document(Document("1","Test","Alice Smith wrote a note.","test"))
    assert r.document.id == "1"
    assert r.tags == ["source/test"]
