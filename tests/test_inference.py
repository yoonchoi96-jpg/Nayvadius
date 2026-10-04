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


def test_cross_domain_link_is_provenance_preserving(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE documents(id TEXT PRIMARY KEY, source TEXT);
    CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT, confidence REAL);
    CREATE TABLE document_vocabulary_links(document_id TEXT, vocabulary_id TEXT, match_type TEXT, confidence REAL);
    CREATE TABLE vocabularies(id TEXT PRIMARY KEY, word TEXT, pinyin TEXT);
    """)
    db.execute("INSERT INTO documents VALUES('doc-1','abraham')")
    db.execute("INSERT INTO document_entities VALUES('doc-1','Taylor Swift','People',1.0)")
    db.execute("INSERT INTO vocabularies VALUES('v1','音乐','yīnyuè')")
    db.execute("INSERT INTO document_vocabulary_links VALUES('doc-1','v1','exact',0.9)")
    db.commit()

    from nayvadius.inference import derive_cross_domain_links
    assert derive_cross_domain_links(db) == 1
    row = db.execute(
        "SELECT left_name,left_type,right_id,confidence,rule,provenance "
        "FROM cross_domain_links"
    ).fetchone()
    assert row[:3] == ("Taylor Swift", "People", "v1")
    assert row[3] == 0.81
    assert row[4] == "same_abraham_document"
    assert json.loads(row[5])["document_ids"] == ["doc-1"]


def test_three_way_abraham_abel_jacques_bridge(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "x.db")
    db.executescript("""
    CREATE TABLE documents(id TEXT PRIMARY KEY, source TEXT);
    CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT, confidence REAL);
    CREATE TABLE document_vocabulary_links(document_id TEXT, vocabulary_id TEXT, match_type TEXT, confidence REAL);
    CREATE TABLE vocabularies(id TEXT PRIMARY KEY, word TEXT, pinyin TEXT);
    CREATE TABLE entities(name TEXT, entity_type TEXT, aliases TEXT, confidence REAL);
    CREATE TABLE relations(source_name TEXT, relation TEXT, target_name TEXT, confidence REAL);
    CREATE TABLE document_relations(document_id TEXT, source_name TEXT, relation TEXT, target_name TEXT, confidence REAL);
    """)
    db.executemany("INSERT INTO documents VALUES(?,?)", [
        ("abraham-1", "abraham"),
        ("jacques-1", "jacques"),
    ])
    db.execute("INSERT INTO document_entities VALUES('abraham-1','Taylor Swift','People',1.0)")
    db.execute("INSERT INTO document_entities VALUES('jacques-1','Taylor Swift','People',1.0)")
    db.execute("INSERT INTO document_entities VALUES('jacques-1','Blank Space','MusicTracks',1.0)")
    db.execute("INSERT INTO document_entities VALUES('jacques-1','1989','MusicAlbums',1.0)")
    db.execute("INSERT INTO vocabularies VALUES('v1','音乐','yīnyuè')")
    db.execute("INSERT INTO document_vocabulary_links VALUES('abraham-1','v1','exact',0.9)")
    db.executemany("INSERT INTO entities VALUES(?,?,?,?)", [
        ("Taylor Swift","People","",1.0),
        ("Blank Space","MusicTracks","",1.0),
        ("1989","MusicAlbums","",1.0),
    ])
    db.execute("INSERT INTO relations VALUES('Taylor Swift','performed','Blank Space',1.0)")
    db.execute("INSERT INTO relations VALUES('Blank Space','part_of','1989',1.0)")
    db.execute("INSERT INTO document_relations VALUES('jacques-1','Taylor Swift','performed','Blank Space',1.0)")
    db.execute("INSERT INTO document_relations VALUES('jacques-1','Blank Space','part_of','1989',1.0)")
    db.commit()

    from nayvadius.inference import derive_cross_domain_links
    assert derive_cross_domain_links(db) == 4

    track = db.execute(
        """SELECT confidence,rule,provenance FROM cross_domain_links
           WHERE left_name='v1' AND right_id='Blank Space'"""
    ).fetchone()
    assert track[0] == 0.729
    assert track[1] == "abraham_entity+abel_vocabulary+jacques_track"
    assert json.loads(track[2])["document_ids"] == ["abraham-1", "jacques-1"]

    album = db.execute(
        """SELECT confidence,rule,provenance FROM cross_domain_links
           WHERE left_name='v1' AND right_id='1989'"""
    ).fetchone()
    assert album[0] == 0.69255
    assert album[1] == "abraham_entity+abel_vocabulary+jacques_track+album"
    assert "jacques-1" in json.loads(album[2])["document_ids"]
