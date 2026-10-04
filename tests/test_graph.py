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

    assert data["schema_version"] == "4"
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
