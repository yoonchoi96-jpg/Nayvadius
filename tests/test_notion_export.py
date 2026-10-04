import json
from pathlib import Path

from nayvadius.db import connect
from nayvadius.notion_export import write_notion_manifest
from nayvadius.inference import derive_cross_domain_links
from nayvadius.source_bridges import derive_source_bridge_links


def test_notion_manifest_is_deterministic_and_keeps_provenance(tmp_path: Path):
    db = connect(tmp_path / "state.db")
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Taylor Swift", "People", "Taylor", 0.95))
    db.execute(
        "INSERT INTO documents(id,title,content_hash,source,status) VALUES(?,?,?,?,?)",
        ("doc-1", "Music note", "hash", "abraham", "done"),
    )
    db.execute(
        "INSERT INTO entity_sources(entity_name,entity_type,source,document_id) VALUES(?,?,?,?)",
        ("Taylor Swift", "People", "abraham", "doc-1"),
    )
    db.commit()
    first = write_notion_manifest(db, tmp_path)
    payload1 = json.loads(Path(first).read_text())
    second = write_notion_manifest(db, tmp_path)
    payload2 = json.loads(Path(second).read_text())
    assert payload1 == payload2
    assert payload1["entities"][0]["id"] == payload2["entities"][0]["id"]
    assert payload1["entities"][0]["provenance"] == [{"source": "abraham", "document_id": "doc-1"}]
    assert payload1["schema_version"] == 2
    assert payload1["upsert_key"] == "id"


def test_notion_manifest_projects_cross_domain_and_source_bridges(tmp_path: Path):
    db = connect(tmp_path / "state.db")
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Taylor Swift", "People", "", 1.0))
    derive_cross_domain_links(db)
    derive_source_bridge_links(db)
    db.execute(
        "INSERT INTO cross_domain_links VALUES(?,?,?,?,?,?,?)",
        ("Taylor Swift", "People", "v1", "vocabulary", 0.9, "same_abraham_document", '{"document_ids":["doc-1"]}'),
    )
    db.execute(
        "INSERT INTO source_bridge_links VALUES(?,?,?,?,?,?,?)",
        ("Taylor Swift", "People", "abraham", "jacques", 1.0, "shared_canonical_entity", '{"sources":{"abraham":{"document_ids":["doc-1"]},"jacques":{"document_ids":["track-1"]}}}'),
    )
    db.commit()
    payload = json.loads(Path(write_notion_manifest(db, tmp_path)).read_text())
    kinds = {(x["kind"], x["relation"]) for x in payload["relations"]}
    assert ("cross_domain", "cross_domain") in kinds
    assert ("source_bridge", "source_bridge") in kinds
