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


def test_derived_music_chain_rebuilds_without_stale_rows(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE document_relations(document_id TEXT,source_name TEXT,relation TEXT,target_name TEXT);
    """)
    db.executemany("INSERT INTO entities VALUES(?,?,?,?)", [
        ("Taylor Swift", "People", "", 1.0),
        ("Blank Space", "MusicTracks", "", 1.0),
        ("1989", "MusicAlbums", "", 1.0),
        ("Folklore", "MusicAlbums", "", 1.0),
    ])
    db.executemany("INSERT INTO relations VALUES(?,?,?,?)", [
        ("Taylor Swift", "performed", "Blank Space", 1.0),
        ("Blank Space", "part_of", "1989", 1.0),
    ])
    db.executemany("INSERT INTO document_relations VALUES(?,?,?,?)", [
        ("doc-a", "Taylor Swift", "performed", "Blank Space"),
        ("doc-b", "Blank Space", "part_of", "1989"),
    ])
    db.commit()

    assert derive_relation_chains(db) == 1
    row = db.execute(
        "SELECT provenance FROM derived_relations "
        "WHERE source_name='Taylor Swift' AND target_name='1989'"
    ).fetchone()
    provenance = json.loads(row[0])
    assert provenance[0]["document_ids"] == ["doc-a"]
    assert provenance[1]["document_ids"] == ["doc-b"]

    db.execute("DELETE FROM relations WHERE target_name='1989'")
    db.commit()
    assert derive_relation_chains(db) == 0
    assert db.execute("SELECT COUNT(*) FROM derived_relations").fetchone()[0] == 0
