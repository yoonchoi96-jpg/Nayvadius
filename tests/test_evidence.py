from pathlib import Path

from nayvadius.db import connect, link_relation_evidence, save_evidence
from nayvadius.evidence import Evidence


def test_evidence_persistence(tmp_path: Path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))
    save_evidence(Evidence("readwise", "rw-1", "Source", "content", "https://example.com"))
    link_relation_evidence("doc-1", "Apple", "acquired", "Beats", "rw-1", "checked")

    with connect() as db:
        evidence = db.execute(
            "SELECT source,title,content,url FROM evidence WHERE document_id='rw-1'"
        ).fetchone()
        relation = db.execute(
            "SELECT document_id,source_name,relation,target_name,evidence_document_id,status "
            "FROM relation_evidence"
        ).fetchone()

    assert evidence == ("readwise", "Source", "content", "https://example.com")
    assert relation == ("doc-1", "Apple", "acquired", "Beats", "rw-1", "checked")


def test_relation_evidence_status_is_persisted(tmp_path: Path, monkeypatch):
    state = tmp_path / "state.db"
    monkeypatch.setattr("nayvadius.config.settings.state_path", str(state))
    link_relation_evidence(
        "doc-1", "Apple", "acquired", "Beats", "rw-2", "contradicted"
    )
    with connect() as db:
        status = db.execute(
            "SELECT status FROM relation_evidence WHERE evidence_document_id='rw-2'"
        ).fetchone()[0]
    assert status == "contradicted"
