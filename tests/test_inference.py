import json
import sqlite3
from pathlib import Path

from nayvadius.graph import write_graph
from nayvadius.inference import derive_relation_chains


def test_derived_music_chain_is_separate_and_traceable(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    """)
    db.execute("INSERT INTO entities VALUES('Taylor Swift','People','',1.0)")
    db.execute("INSERT INTO entities VALUES('Blank Space','MusicTracks','',1.0)")
    db.execute("INSERT INTO entities VALUES('1989','MusicAlbums','',1.0)")
    db.execute("INSERT INTO relations VALUES('Taylor Swift','performed','Blank Space',1.0)")
    db.execute("INSERT INTO relations VALUES('Blank Space','part_of','1989',1.0)")
    db.commit()

    assert derive_relation_chains(db) == 1
    write_graph(db, tmp_path / "output")
    data = json.loads((tmp_path / "output" / "graph.json").read_text())
    derived = [x for x in data["edges"] if x.get("kind") == "derived"]

    assert derived[0]["relation"] == "contributed_to"
    assert derived[0]["rule"] == "performed+part_of"
    assert len(derived[0]["provenance"]) == 2
