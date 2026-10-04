import hashlib
import json
from pathlib import Path


def _page_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:32]


def _table_exists(db, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def write_notion_manifest(db, root: str) -> str:
    """Write a deterministic, API-agnostic Notion projection manifest.

    This is a projection of canonical state, not a second database. Stable page
    IDs let a future Notion writer upsert pages without creating duplicates.
    Raw/derived provenance is retained in the payload.
    """
    out = Path(root) / "notion" / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    entities = []
    for name, entity_type, aliases, confidence in db.execute(
        "SELECT name,entity_type,aliases,confidence FROM entities ORDER BY entity_type,name"
    ):
        provenance = []
        if _table_exists(db, "entity_sources"):
            provenance = [
                {"source": source, "document_id": document_id}
                for source, document_id in db.execute(
                    "SELECT source,document_id FROM entity_sources "
                    "WHERE entity_name=? AND entity_type=? ORDER BY source,document_id",
                    (name, entity_type),
                )
            ]
        entities.append({
            "id": _page_id("entity", f"{entity_type}:{name}"),
            "kind": "entity",
            "name": name,
            "entity_type": entity_type,
            "aliases": [x.strip() for x in (aliases or "").split(",") if x.strip()],
            "confidence": confidence,
            "provenance": provenance,
        })

    documents = []
    document_columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
    optional = []
    if "importance" in document_columns:
        optional.append("importance")
    if "document_type" in document_columns:
        optional.append("document_type")
    select_columns = ["id", "title", "source", *optional]
    for row in db.execute(f"SELECT {','.join(select_columns)} FROM documents ORDER BY id"):
        values = dict(zip(select_columns, row))
        document_id = values["id"]
        documents.append({
            "id": _page_id("document", document_id),
            "kind": "document",
            "document_id": document_id,
            "title": values["title"],
            "source": values["source"],
            "importance": values.get("importance"),
            "document_type": values.get("document_type"),
        })

    relations = []
    for source_name, relation, target_name, confidence in db.execute(
        "SELECT source_name,relation,target_name,confidence "
        "FROM relations ORDER BY source_name,relation,target_name"
    ):
        relations.append({
            "source": source_name,
            "relation": relation,
            "target": target_name,
            "confidence": confidence,
            "kind": "raw",
        })

    if _table_exists(db, "derived_relations"):
        for source_name, relation, target_name, confidence, rule, provenance in db.execute(
            "SELECT source_name,relation,target_name,confidence,rule,provenance "
            "FROM derived_relations ORDER BY source_name,relation,target_name,rule"
        ):
            relations.append({
                "source": source_name,
                "relation": relation,
                "target": target_name,
                "confidence": confidence,
                "kind": "derived",
                "rule": rule,
                "provenance": json.loads(provenance),
            })

    if _table_exists(db, "cross_domain_links"):
        for left_name, left_type, right_id, right_kind, confidence, rule, provenance in db.execute(
            "SELECT left_name,left_type,right_id,right_kind,confidence,rule,provenance "
            "FROM cross_domain_links ORDER BY left_name,right_kind,right_id"
        ):
            relations.append({
                "id": _page_id("cross_domain", f"{left_type}:{left_name}:{right_kind}:{right_id}:{rule}"),
                "source": left_name,
                "source_type": left_type,
                "relation": "cross_domain",
                "target": right_id,
                "target_kind": right_kind,
                "confidence": confidence,
                "kind": "cross_domain",
                "rule": rule,
                "provenance": json.loads(provenance),
            })

    if _table_exists(db, "source_bridge_links"):
        for name, entity_type, source_a, source_b, confidence, rule, provenance in db.execute(
            "SELECT entity_name,entity_type,source_a,source_b,confidence,rule,provenance "
            "FROM source_bridge_links ORDER BY entity_type,name,source_a,source_b"
        ):
            relations.append({
                "id": _page_id("source_bridge", f"{entity_type}:{name}:{source_a}:{source_b}:{rule}"),
                "source": name,
                "source_type": entity_type,
                "relation": "source_bridge",
                "target": f"{source_a}↔{source_b}",
                "target_kind": "source_pair",
                "confidence": confidence,
                "kind": "source_bridge",
                "rule": rule,
                "provenance": json.loads(provenance),
            })

    vocabularies = []
    if _table_exists(db, "vocabularies"):
        for row in db.execute(
            "SELECT id,word,traditional,pinyin,pos,meaning_ko,source "
            "FROM vocabularies ORDER BY id"
        ):
            vocabulary_id, word, traditional, pinyin, pos, meaning_ko, source = row
            vocabularies.append({
                "id": _page_id("vocabulary", vocabulary_id),
                "kind": "vocabulary",
                "vocabulary_id": vocabulary_id,
                "word": word,
                "traditional": traditional or "",
                "pinyin": pinyin or "",
                "pos": pos or "",
                "meaning_ko": meaning_ko or "",
                "source": source,
            })

    payload = {
        "schema_version": 2,
        "upsert_key": "id",
        "notion_database_types": ["entity", "document", "relation", "vocabulary"],
        "projection": "notion",
        "generated_by": "nayvadius",
        "entities": entities,
        "documents": documents,
        "relations": relations,
        "vocabularies": vocabularies,
    }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return str(out)
