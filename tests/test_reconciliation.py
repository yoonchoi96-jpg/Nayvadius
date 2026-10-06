from pathlib import Path
import hashlib
import sqlite3

from nayvadius.obsidian_audit import snapshot_vault
from nayvadius.reconciliation import build_db_reconciliation_plan


def _db(path, rows):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE documents(id TEXT, title TEXT, content_hash TEXT, source TEXT)")
        conn.execute("CREATE TABLE document_entities(document_id TEXT, entity_name TEXT, entity_type TEXT)")
        conn.execute("CREATE TABLE entity_aliases(alias TEXT NOT NULL, canonical_name TEXT NOT NULL, entity_type TEXT NOT NULL)")
        conn.execute("CREATE TABLE entities(name TEXT, entity_type TEXT, aliases TEXT)")
        conn.executemany("INSERT INTO documents VALUES(?,?,?,?)", rows)


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_unique_db_hash_move_is_auto(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)

    assert plan["summary"]["auto"] == 1
    item = plan["auto"][0]
    assert item["document_id"] == "doc-1"
    assert item["entities"] == [("Alice", "People")]


def test_ambiguous_db_hash_move_is_review(tmp_path: Path):
    db = tmp_path / "state.db"
    digest = _hash("same")
    _db(db, [("doc-1", "A", digest, "x"), ("doc-2", "B", digest, "y")])

    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)

    assert plan["summary"]["auto"] == 0
    assert plan["review"][0]["db_check"] == "ambiguous DB content_hash match"


def test_missing_db_keeps_move_in_review(tmp_path: Path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "old.md").write_text("same", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "old.md").rename(root / "new.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), tmp_path / "missing.db")

    assert plan["summary"]["auto"] == 0
    assert plan["summary"]["review"] == 1
    assert plan["skipped"][0]["kind"] == "db"


def test_modified_note_keeps_previous_db_identity(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("before"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("before", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").write_text("after", encoding="utf-8")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)
    item = next(x for x in plan["review"] if x["kind"] == "modified")

    assert item["document_id"] == "doc-1"
    assert item["previous_db_entities"] == [("Alice", "People")]
    assert item["identity_status"] == "stale"


def test_added_note_reports_existing_db_match_as_review(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("new"), "readwise")])

    root = tmp_path / "vault"
    root.mkdir()
    previous = snapshot_vault(root)
    (root / "added.md").write_text("new", encoding="utf-8")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db)
    item = plan["review"][0]

    assert item["kind"] == "added"
    assert item["document_id"] == "doc-1"
    assert item["db_check"] == "hash matches existing DB document; path identity is new"


def test_move_requires_canonical_entity_and_wikilink_resolution_when_live_vault_is_available(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    (root / "entities" / "People").mkdir(parents=True)
    (root / "entities" / "People" / "Alice.md").write_text("---\nname: Alice\n---\n", encoding="utf-8")
    (root / "note.md").write_text("[[Alice]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)
    item = plan["auto"][0]
    assert item["document_id"] == "doc-1"
    assert item["entity_resolution"]["resolved"][0]["file"] == "entities/People/Alice.md"
    assert item["wikilink_resolution"]["links"][0]["canonical_file"] == "entities/People/Alice.md"


def test_move_is_review_when_db_entity_has_no_canonical_vault_file(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice','People')")

    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("plain", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)
    assert plan["summary"]["auto"] == 0
    assert plan["review"][0]["db_check"] == "DB identity matched but canonical entity/link resolution is incomplete"


def test_entity_table_alias_metadata_resolves_to_canonical(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Microsoft','Organizations')")
        conn.execute(
            "INSERT INTO entities VALUES('Microsoft','Organizations','[\"MSFT\"]')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "MSFT.md").write_text(
        "---\nname: MSFT\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[MSFT]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)

    assert plan["summary"]["auto"] == 1
    resolution = plan["auto"][0]["entity_resolution"]["resolved"][0]
    assert resolution["resolution_method"] == "db_alias"
    assert resolution["canonical_name"] == "MSFT"


def test_move_resolves_db_entity_alias_to_canonical_vault_entity(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Alice Corp','Organizations')")
        conn.execute(
            "INSERT INTO entity_aliases VALUES('Alice Corp','Alice Corporation','Organizations')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "Alice Corporation.md").write_text(
        "---\nname: Alice Corporation\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[Alice Corporation]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)

    assert plan["summary"]["auto"] == 1
    resolution = plan["auto"][0]["entity_resolution"]["resolved"][0]
    assert resolution["resolution_method"] == "db_alias"
    assert resolution["db_alias"] == "Alice Corp"
    assert resolution["canonical_name"] == "Alice Corporation"


def test_conflicting_db_entity_aliases_force_review(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Acme','Organizations')")
        conn.executemany(
            "INSERT INTO entity_aliases VALUES(?,?,?)",
            [
                ("Acme", "Acme Holdings", "Organizations"),
                ("Acme", "Acme Corp", "Organizations"),
            ],
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    for name in ("Acme Holdings", "Acme Corp"):
        (root / "entities" / "Organizations" / f"{name}.md").write_text(
            f"---\nname: {name}\n---\n", encoding="utf-8"
        )
    (root / "note.md").write_text("[[Acme Holdings]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)

    assert plan["summary"]["auto"] == 0
    entity_check = plan["review"][0]["entity_resolution"]
    assert entity_check["unresolved"][0]["reason"] == "conflicting DB entity_aliases mappings"
    assert entity_check["unresolved"][0]["canonical_names"] == ["Acme Corp", "Acme Holdings"]


def test_db_alias_type_mismatch_does_not_resolve(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Apple','Organizations')")
        conn.execute(
            "INSERT INTO entity_aliases VALUES('Apple','Apple Inc.','Companies')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "Apple Inc..md").write_text(
        "---\nname: Apple Inc.\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[Apple Inc.]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)

    assert plan["summary"]["auto"] == 0
    unresolved = plan["review"][0]["entity_resolution"]["unresolved"][0]
    assert unresolved["reason"] == "no canonical Obsidian entity file or DB alias match"


def test_db_alias_resolution_records_explicit_alias_source(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Acme','Organizations')")
        conn.execute(
            "INSERT INTO entity_aliases VALUES('Acme','Acme Corporation','Organizations')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "Acme Corporation.md").write_text(
        "---\nname: Acme Corporation\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[Acme Corporation]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)
    resolution = plan["auto"][0]["entity_resolution"]["resolved"][0]

    assert resolution["resolution_method"] == "db_alias"
    assert resolution["alias_sources"] == ["entity_aliases"]


def test_entity_table_alias_resolution_records_metadata_alias_source(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Acme','Organizations')")
        conn.execute(
            "INSERT INTO entities VALUES('Acme','Organizations','[\"Acme Corporation\"]')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "Acme Corporation.md").write_text(
        "---\nname: Acme Corporation\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[Acme Corporation]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)
    resolution = plan["auto"][0]["entity_resolution"]["resolved"][0]

    assert resolution["resolution_method"] == "db_alias"
    assert resolution["alias_sources"] == ["entities.aliases"]


def test_matching_alias_sources_are_both_recorded(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Acme','Organizations')")
        conn.execute(
            "INSERT INTO entity_aliases VALUES('Acme','Acme Corporation','Organizations')"
        )
        conn.execute(
            "INSERT INTO entities VALUES('Acme','Organizations','[\"Acme Corporation\"]')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    (root / "entities" / "Organizations" / "Acme Corporation.md").write_text(
        "---\nname: Acme Corporation\n---\n", encoding="utf-8"
    )
    (root / "note.md").write_text("[[Acme Corporation]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)
    resolution = plan["auto"][0]["entity_resolution"]["resolved"][0]

    assert resolution["alias_sources"] == ["entities.aliases", "entity_aliases"]


def test_conflicting_alias_sources_force_review(tmp_path: Path):
    db = tmp_path / "state.db"
    _db(db, [("doc-1", "Note", _hash("same"), "readwise")])
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO document_entities VALUES('doc-1','Acme','Organizations')")
        conn.execute(
            "INSERT INTO entity_aliases VALUES('Acme','Acme Holdings','Organizations')"
        )
        conn.execute(
            "INSERT INTO entities VALUES('Acme','Organizations','[\"Acme Corp\"]')"
        )

    root = tmp_path / "vault"
    (root / "entities" / "Organizations").mkdir(parents=True)
    for name in ("Acme Holdings", "Acme Corp"):
        (root / "entities" / "Organizations" / f"{name}.md").write_text(
            f"---\nname: {name}\n---\n", encoding="utf-8"
        )
    (root / "note.md").write_text("[[Acme Holdings]]", encoding="utf-8")
    previous = snapshot_vault(root)
    (root / "note.md").rename(root / "renamed.md")

    plan = build_db_reconciliation_plan(previous, snapshot_vault(root), db, vault_root=root)

    assert plan["summary"]["auto"] == 0
    entity_check = plan["review"][0]["entity_resolution"]
    assert entity_check["unresolved"][0]["reason"] == "conflicting DB entity alias mappings"
    assert entity_check["unresolved"][0]["canonical_names"] == ["Acme Corp", "Acme Holdings"]
