import sqlite3
from pathlib import Path

from nayvadius.db import connect


def test_legacy_document_schema_adds_content_column_without_losing_rows(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE documents(id TEXT PRIMARY KEY,title TEXT NOT NULL,"
        "content_hash TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,"
        "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        "INSERT INTO documents(id,title,content_hash,source,status) "
        "VALUES('doc-1','Title','hash','abraham','done')"
    )
    db.commit()
    db.close()

    with connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
        assert "content" in columns
        assert db.execute(
            "SELECT id,title,content FROM documents"
        ).fetchall() == [("doc-1", "Title", "")]


def test_legacy_company_brand_migration_preserves_links_and_provenance(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    db = sqlite3.connect(db_path)
    db.executescript("""
    CREATE TABLE entities(
        name TEXT NOT NULL, entity_type TEXT NOT NULL, aliases TEXT,
        confidence REAL NOT NULL, PRIMARY KEY(name,entity_type)
    );
    CREATE TABLE document_entities(
        document_id TEXT NOT NULL, entity_name TEXT NOT NULL,
        entity_type TEXT NOT NULL, confidence REAL NOT NULL,
        PRIMARY KEY(document_id,entity_name,entity_type)
    );
    CREATE TABLE entity_sources(
        entity_name TEXT NOT NULL, entity_type TEXT NOT NULL,
        source TEXT NOT NULL, document_id TEXT NOT NULL,
        PRIMARY KEY(entity_name,entity_type,source,document_id)
    );
    CREATE TABLE entity_aliases(
        alias TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, entity_type TEXT NOT NULL
    );
    """)
    db.execute("INSERT INTO entities VALUES('Acme','Companies','Acme Corp',0.7)")
    db.execute("INSERT INTO entities VALUES('Acme','Organizations','Acme',0.9)")
    db.execute("INSERT INTO entities VALUES('Foo','Brands','Foo Label',0.8)")
    db.execute("INSERT INTO document_entities VALUES('doc-c','Acme','Companies',0.7)")
    db.execute("INSERT INTO document_entities VALUES('doc-o','Acme','Organizations',0.9)")
    db.execute("INSERT INTO document_entities VALUES('doc-b','Foo','Brands',0.8)")
    db.execute("INSERT INTO entity_sources VALUES('Acme','Companies','abraham','doc-c')")
    db.execute("INSERT INTO entity_sources VALUES('Acme','Organizations','jacques','doc-o')")
    db.execute("INSERT INTO entity_sources VALUES('Foo','Brands','abraham','doc-b')")
    db.execute("INSERT INTO entity_aliases VALUES('acme corp','Acme','Companies')")
    db.execute("INSERT INTO entity_aliases VALUES('acme','Acme','Organizations')")
    db.execute("INSERT INTO entity_aliases VALUES('foo label','Foo','Brands')")
    db.commit()
    db.close()

    db = connect(db_path)
    assert db.execute(
        "SELECT name,entity_type,confidence FROM entities ORDER BY name"
    ).fetchall() == [
        ("Acme","Organizations",0.9),
        ("Foo","Organizations",0.8),
    ]
    assert db.execute(
        "SELECT document_id,entity_name,entity_type FROM document_entities ORDER BY document_id"
    ).fetchall() == [
        ("doc-b","Foo","Organizations"),
        ("doc-c","Acme","Organizations"),
        ("doc-o","Acme","Organizations"),
    ]
    assert db.execute(
        "SELECT entity_name,entity_type,source,document_id FROM entity_sources ORDER BY document_id"
    ).fetchall() == [
        ("Foo","Organizations","abraham","doc-b"),
        ("Acme","Organizations","abraham","doc-c"),
        ("Acme","Organizations","jacques","doc-o"),
    ]
    aliases = db.execute(
        "SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY alias"
    ).fetchall()
    assert aliases == [
        ("acme","Acme","Organizations"),
        ("acme corp","Acme","Organizations"),
        ("foo label","Foo","Organizations"),
    ]
    db.close()


def test_company_brand_migration_preserves_type_isolated_aliases(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    db = sqlite3.connect(db_path)
    db.executescript("""
    CREATE TABLE entities(
        name TEXT NOT NULL, entity_type TEXT NOT NULL, aliases TEXT,
        confidence REAL NOT NULL, PRIMARY KEY(name,entity_type)
    );
    CREATE TABLE document_entities(
        document_id TEXT NOT NULL, entity_name TEXT NOT NULL,
        entity_type TEXT NOT NULL, confidence REAL NOT NULL,
        PRIMARY KEY(document_id,entity_name,entity_type)
    );
    CREATE TABLE entity_sources(
        entity_name TEXT NOT NULL, entity_type TEXT NOT NULL,
        source TEXT NOT NULL, document_id TEXT NOT NULL,
        PRIMARY KEY(entity_name,entity_type,source,document_id)
    );
    CREATE TABLE entity_aliases(
        alias TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, entity_type TEXT NOT NULL
    );
    """)
    db.execute("INSERT INTO entities VALUES('Apple','Companies','apple',0.8)")
    db.execute("INSERT INTO entities VALUES('Apple','Products','Apple device',0.9)")
    db.execute("INSERT INTO entity_aliases VALUES('apple','Apple','Companies')")
    db.commit()
    db.close()

    db = connect(db_path)
    assert db.execute(
        "SELECT alias,canonical_name,entity_type FROM entity_aliases ORDER BY entity_type"
    ).fetchall() == [
        ("apple","Apple","Organizations"),
    ]
    db.close()
