import json
import sqlite3
from pathlib import Path
from nayvadius.graph import write_graph

def test_graph_export(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    """)
    db.execute("INSERT INTO entities VALUES('Ada Lovelace','People','Ada',0.9)")
    db.execute("INSERT INTO entities VALUES('Analytical Engine','Products','',0.8)")
    db.execute("INSERT INTO relations VALUES('Ada Lovelace','worked_on','Analytical Engine',0.8)")
    db.commit()

    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())

    assert data["schema_version"] == "7"
    assert data["edges"][0]["source"] == "People:Ada Lovelace"
    assert data["edges"][0]["target"] == "Products:Analytical Engine"
    assert data["edges"][0]["relation"] == "worked_on"

def test_graph_includes_relation_evidence(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE relation_evidence(
        document_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        relation TEXT NOT NULL,
        target_name TEXT NOT NULL,
        evidence_document_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'checked'
    );
    """)
    db.execute("INSERT INTO entities VALUES('Apple','Companies','',0.9)")
    db.execute("INSERT INTO entities VALUES('Beats','Brands','',0.8)")
    db.execute("INSERT INTO relations VALUES('Apple','acquired','Beats',0.95)")
    db.execute("INSERT INTO relation_evidence VALUES('doc-1','Apple','acquired','Beats','rw-123','checked')")
    db.commit()

    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())
    assert data["edges"][0]["evidence"] == [{"document_id": "rw-123", "status": "checked"}]

def test_graph_skips_ambiguous_endpoint(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE relation_evidence(
        document_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        relation TEXT NOT NULL,
        target_name TEXT NOT NULL,
        evidence_document_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'checked'
    );
    """)
    db.execute("INSERT INTO entities VALUES('Apple','Companies','',0.9)")
    db.execute("INSERT INTO entities VALUES('Apple','Brands','',0.9)")
    db.execute("INSERT INTO entities VALUES('Steve Jobs','People','',0.9)")
    db.execute("INSERT INTO relations VALUES('Steve Jobs','founded','Apple',0.8)")
    db.commit()

    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())
    assert data["edges"] == []


def test_graph_exports_cross_domain_vocabulary_and_music_edges(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE vocabularies(id TEXT PRIMARY KEY,word TEXT,traditional TEXT,pinyin TEXT,source TEXT);
    CREATE TABLE cross_domain_links(
        left_name TEXT,left_type TEXT,right_id TEXT,right_kind TEXT,
        confidence REAL,rule TEXT,provenance TEXT,
        PRIMARY KEY(left_name,left_type,right_id,right_kind,rule)
    );
    """)
    db.execute("INSERT INTO entities VALUES('Taylor Swift','People','',1.0)")
    db.execute("INSERT INTO entities VALUES('Blank Space','MusicTracks','',1.0)")
    db.execute("INSERT INTO vocabularies VALUES('v1','音乐','','yīnyuè','abel')")
    db.execute(
        """INSERT INTO cross_domain_links VALUES(
           'Taylor Swift','People','v1','vocabulary',0.81,
           'same_abraham_document','{"document_ids":["abraham-1"]}')"""
    )
    db.execute(
        """INSERT INTO cross_domain_links VALUES(
           'v1','Vocabulary','Blank Space','music_track',0.729,
           'abraham_entity+abel_vocabulary+jacques_track',
           '{"document_ids":["abraham-1","jacques-1"]}')"""
    )
    db.commit()

    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())
    assert "Vocabulary:v1" in {n["id"] for n in data["nodes"]}
    cross = [e for e in data["edges"] if e.get("kind") == "cross_domain"]
    assert len(cross) == 2
    assert any(e["source"] == "People:Taylor Swift" and e["target"] == "Vocabulary:v1" for e in cross)
    assert any(e["source"] == "Vocabulary:v1" and e["target"] == "MusicTracks:Blank Space" for e in cross)


def test_entity_aliases_are_isolated_by_type(tmp_path: Path):
    from nayvadius.db import connect, save_entity_alias
    db_path = tmp_path / "state.db"
    db = connect(db_path)
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Apple", "Organizations", "", 1.0))
    db.execute("INSERT INTO entities VALUES(?,?,?,?)", ("Apple", "Products", "", 1.0))
    db.commit()
    db.close()

    save_entity_alias("apple", "Apple", "Organizations")
    save_entity_alias("apple", "Apple", "Products")

    db = connect(db_path)
    rows = db.execute(
        "SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY entity_type"
    ).fetchall()
    assert rows == [
        ("apple", "Apple", "Organizations"),
        ("apple", "Apple", "Products"),
    ]
    db.close()
