import json
import sqlite3
from pathlib import Path

from nayvadius.qa import audit_database, write_report


def _db(path: Path):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE documents(id TEXT PRIMARY KEY,title TEXT,content_hash TEXT,source TEXT,status TEXT,updated_at TEXT);
    CREATE TABLE results(document_id TEXT PRIMARY KEY,payload TEXT);
    CREATE TABLE entities(name TEXT,entity_type TEXT,aliases TEXT,confidence REAL,PRIMARY KEY(name,entity_type));
    CREATE TABLE document_entities(document_id TEXT,entity_name TEXT,entity_type TEXT,confidence REAL);
    CREATE TABLE relations(source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE document_relations(document_id TEXT,source_name TEXT,relation TEXT,target_name TEXT,confidence REAL);
    CREATE TABLE evidence(document_id TEXT PRIMARY KEY,source TEXT,title TEXT,content TEXT,url TEXT,checked_at TEXT);
    CREATE TABLE relation_evidence(document_id TEXT,source_name TEXT,relation TEXT,target_name TEXT,evidence_document_id TEXT,status TEXT,checked_at TEXT);
    CREATE TABLE entity_aliases(alias TEXT,canonical_name TEXT,entity_type TEXT);
    CREATE TABLE entity_sources(entity_name TEXT,entity_type TEXT,source TEXT,document_id TEXT);
    CREATE TABLE entity_merge_log(id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_name TEXT,duplicate_name TEXT,entity_type TEXT,reason TEXT,created_at TEXT);
    CREATE TABLE processing_failures(document_id TEXT PRIMARY KEY,attempts INTEGER,last_error TEXT,next_retry_at TEXT,updated_at TEXT);
    CREATE TABLE vocabularies(id TEXT PRIMARY KEY,word TEXT,traditional TEXT,pinyin TEXT,pos TEXT,meaning_ko TEXT,hsk_levels TEXT,wordbooks TEXT,source TEXT,metadata TEXT,updated_at TEXT);
    CREATE TABLE entity_vocabulary_links(entity_name TEXT,entity_type TEXT,vocabulary_id TEXT,match_type TEXT,confidence REAL);
    CREATE TABLE document_vocabulary_links(document_id TEXT,vocabulary_id TEXT,match_type TEXT,confidence REAL);
    CREATE TABLE vocabulary_sources(vocabulary_id TEXT,source_id TEXT,source TEXT,metadata TEXT);
    """)
    return db


def test_clean_database_passes(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.execute("INSERT INTO documents VALUES('d1','Doc','h','readwise','ok','now')")
    db.execute("INSERT INTO entities VALUES('Apple','Organizations','',0.9)")
    db.execute("INSERT INTO entities VALUES('Beats','Organizations','',0.8)")
    db.execute("INSERT INTO relations VALUES('Apple','acquired','Beats',0.95)")
    db.execute("INSERT INTO document_entities VALUES('d1','Apple','Organizations',0.9)")
    db.execute("INSERT INTO evidence VALUES('e1','readwise','Evidence','text','https://x','now')")
    db.execute("INSERT INTO relation_evidence VALUES('d1','Apple','acquired','Beats','e1','checked','now')")
    db.commit()
    db.close()

    report = audit_database(path)
    assert report["status"] == "PASS"
    assert report["summary"]["errors"] == 0


def test_qa_detects_orphan_relation_and_bad_type(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.execute("INSERT INTO documents VALUES('d1','Doc','h','readwise','ok','now')")
    db.execute("INSERT INTO entities VALUES('Apple','Companies','',0.9)")
    db.execute("INSERT INTO relations VALUES('Apple','acquired','Missing',1.2)")
    db.commit()
    db.close()

    report = audit_database(path)
    rules = {f["rule"] for f in report["findings"]}
    assert report["status"] == "FAIL"
    assert "entity.invalid_type" in rules
    assert "relation.orphan_endpoint" in rules
    assert "relation.confidence_range" in rules


def test_alias_collision_is_warning_not_failure(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.execute("INSERT INTO documents VALUES('d1','Doc','h','readwise','ok','now')")
    db.execute("INSERT INTO entities VALUES('Apple Inc.','Organizations','apple',0.9)")
    db.execute("INSERT INTO entities VALUES('Apple Records','Organizations','apple',0.8)")
    db.execute("INSERT INTO entity_aliases VALUES('apple','Apple Inc.','Organizations')")
    db.execute("INSERT INTO entity_aliases VALUES('apple','Apple Records','Organizations')")
    db.commit()
    db.close()

    report = audit_database(path)
    assert report["status"] == "PASS"
    assert report["summary"]["warnings"] == 1
    assert report["findings"][0]["rule"] == "alias.ambiguous"


def test_orphan_alias_fails_qa(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.execute("INSERT INTO entity_aliases VALUES('orphan','Missing Entity','Concepts')")
    db.commit()
    db.close()

    report = audit_database(path)
    assert report["status"] == "FAIL"
    assert "alias.orphan" in {finding["rule"] for finding in report["findings"]}


def test_report_is_json(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.commit()
    db.close()
    report = audit_database(path)
    out = tmp_path / "qa.json"
    write_report(report, out)
    assert json.loads(out.read_text())["status"] == "PASS"
