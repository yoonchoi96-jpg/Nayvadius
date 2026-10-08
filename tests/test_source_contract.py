import pytest

from nayvadius.models import Document
from nayvadius.source_contract import build_source_identity, validate_source_identity


def test_source_identity_prefers_explicit_external_id():
    doc = Document(
        "canonical-doc",
        "Title",
        "body",
        source="Abraham",
        metadata={"external_id": "reader-42", "plugin_version": "1"},
    )
    identity = validate_source_identity(doc)
    assert identity.source == "abraham"
    assert identity.source_id == "reader-42"
    assert identity.metadata["plugin_version"] == "1"
    assert identity.metadata["source"] == "abraham"


def test_source_identity_falls_back_to_document_id():
    doc = Document("track-1", "Track", "body", source="jacques")
    identity = validate_source_identity(doc)
    assert identity.source_id == "track-1"


def test_missing_source_is_rejected():
    doc = Document("d1", "Title", "body", source="")
    with pytest.raises(ValueError, match="source and source_id"):
        validate_source_identity(doc)


def test_missing_source_id_is_rejected():
    doc = Document("", "Title", "body", source="abel")
    assert build_source_identity(doc) is None
