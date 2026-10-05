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


def test_qa_validates_provenance_and_cross_domain_graph_links(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.execute("INSERT INTO entities VALUES('Taylor Swift','People','',1.0)")
    db.execute("INSERT INTO documents VALUES('d1','Doc','h','abraham','ok','now')")
    db.execute(
        "INSERT INTO entity_sources VALUES('Missing Entity','People','jacques','missing-doc')"
    )
    db.execute(
        "INSERT INTO entity_vocabulary_links VALUES('Taylor Swift','People','missing-vocab','exact',1.2)"
    )
    db.execute(
        "INSERT INTO document_vocabulary_links VALUES('missing-doc','missing-vocab','exact',-0.1)"
    )
    db.execute(
        "INSERT INTO vocabulary_sources VALUES('missing-vocab','source-1','abel','{}')"
    )
    db.executescript("""
    CREATE TABLE derived_relations(
        source_name TEXT,relation TEXT,target_name TEXT,confidence REAL,
        rule TEXT,provenance TEXT
    );
    CREATE TABLE cross_domain_links(
        left_name TEXT,left_type TEXT,right_id TEXT,right_kind TEXT,
        confidence REAL,rule TEXT,provenance TEXT
    );
    CREATE TABLE source_bridge_links(
        entity_name TEXT,entity_type TEXT,source_a TEXT,source_b TEXT,
        confidence REAL,rule TEXT,provenance TEXT
    );
    """)
    db.execute(
        "INSERT INTO derived_relations VALUES('Taylor Swift','derived_to','Missing',1.5,'r','[]')"
    )
    db.execute(
        "INSERT INTO cross_domain_links VALUES('Taylor Swift','People','missing-vocab','vocabulary',1.4,'r','{}')"
    )
    db.execute(
        "INSERT INTO source_bridge_links VALUES('Missing Entity','People','abel','abel',-1,'r','{}')"
    )
    db.commit()
    db.close()

    report = audit_database(path)
    rules = {finding["rule"] for finding in report["findings"]}
    assert report["status"] == "FAIL"
    assert {
        "entity_source.orphan",
        "entity_vocabulary.orphan",
        "entity_vocabulary.confidence_range",
        "document_vocabulary.orphan",
        "document_vocabulary.confidence_range",
        "vocabulary_source.orphan",
        "derived_relation.orphan_endpoint",
        "derived_relation.confidence_range",
        "cross_domain_link.orphan_endpoint",
        "cross_domain_link.confidence_range",
        "source_bridge.invalid_endpoint",
        "source_bridge.confidence_range",
    } <= rules


def test_report_is_json(tmp_path: Path):
    path = tmp_path / "qa.db"
    db = _db(path)
    db.commit()
    db.close()
    report = audit_database(path)
    out = tmp_path / "qa.json"
    write_report(report, out)
    assert json.loads(out.read_text())["status"] == "PASS"
