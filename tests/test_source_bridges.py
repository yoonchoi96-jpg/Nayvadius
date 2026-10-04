import json
import sqlite3
from pathlib import Path

from nayvadius.source_bridges import derive_source_bridge_links
from nayvadius.graph import write_graph

def test_source_bridge_pairwise_provenance(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("CREATE TABLE entity_sources(entity_name TEXT,entity_type TEXT,source TEXT,document_id TEXT);")
    db.executemany("INSERT INTO entity_sources VALUES(?,?,?,?)", [
        ("Taylor Swift","People","abraham","a1"),
        ("Taylor Swift","People","abraham","a2"),
        ("Taylor Swift","People","jacques","j1"),
        ("Taylor Swift","People","abel","v1"),
    ])
    db.commit()
    assert derive_source_bridge_links(db) == 3
    row = db.execute("SELECT confidence,rule,provenance FROM source_bridge_links WHERE source_a=? AND source_b=?", ("abraham","jacques")).fetchone()
    assert row[0] == 1.0
    assert row[1] == "shared_canonical_entity"
    payload = json.loads(row[2])
    assert payload["sources"]["abraham"]["document_ids"] == ["a1","a2"]
    assert payload["sources"]["jacques"]["document_ids"] == ["j1"]

def test_graph_exports_source_bridge(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL); CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL); CREATE TABLE source_bridge_links(entity_name TEXT,entity_type TEXT,source_a TEXT,source_b TEXT,confidence REAL,rule TEXT,provenance TEXT);")
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Taylor Swift","People","",1.0))
    db.execute("INSERT INTO source_bridge_links VALUES(?,?,?,?,?,?,?)", ("Taylor Swift","People","abraham","jacques",1.0,"shared_canonical_entity",json.dumps({"sources":{"abraham":{"document_ids":["a1"]},"jacques":{"document_ids":["j1"]}}})))
    db.commit()
    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())
    assert data["schema_version"] == "7"
    edges = [e for e in data["edges"] if e.get("kind") == "source_bridge"]
    assert len(edges) == 1
    assert edges[0]["source"] == "People:Taylor Swift"