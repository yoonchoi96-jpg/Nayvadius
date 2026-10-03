import json
import sqlite3
from pathlib import Path
from nayvadius.graph import write_graph

def test_graph_export(tmp_path: Path):
    db=sqlite3.connect(tmp_path/"x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    """)
    db.execute("INSERT INTO entities VALUES('Ada Lovelace','People','Ada',0.9)")
    db.execute("INSERT INTO relations VALUES('Ada Lovelace','worked_on','Analytical Engine',0.8)")
    db.commit()
    write_graph(db,tmp_path/"output")
    data=json.loads((tmp_path/"output"/"graph.json").read_text())
    assert data["nodes"][0]["type"]=="People"
    assert data["edges"][0]["relation"]=="worked_on"
