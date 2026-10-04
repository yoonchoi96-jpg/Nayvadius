import json
from pathlib import Path

def _canonical_id(rows, db):
    by_name = {}
    for name, entity_type, aliases, confidence in rows:
        node_id = f"{entity_type}:{name}"
        if node_id not in by_name.setdefault(name, []):
            by_name[name].append(node_id)
        for alias in (aliases or "").split(","):
            alias = alias.strip()
            if alias and node_id not in by_name.setdefault(alias, []):
                by_name[alias].append(node_id)
    try:
        alias_rows = db.execute("SELECT alias,canonical_name,entity_type FROM entity_aliases")
    except Exception as exc:
        if "no such table" in str(exc):
            alias_rows = []
        else:
            raise
    for alias, canonical_name, entity_type in alias_rows:
        node_id = f"{entity_type}:{canonical_name}"
        if node_id in by_name.get(canonical_name, []) and node_id not in by_name.setdefault(alias, []):
            by_name[alias].append(node_id)
    return by_name

def write_graph(db, root):
    rows = list(db.execute(
        "SELECT name,entity_type,aliases,confidence FROM entities"
    ))
    nodes = {}
    for name, entity_type, aliases, confidence in rows:
        node_id = f"{entity_type}:{name}"
        try:
            provenance = [{"source": s, "document_id": d} for s, d in db.execute("SELECT source,document_id FROM entity_sources WHERE entity_name=? AND entity_type=? ORDER BY source,document_id", (name, entity_type))]
        except Exception as exc:
            if "no such table" in str(exc):
                provenance = []
            else:
                raise
        nodes[node_id] = {
            "id": node_id,
            "name": name,
            "type": entity_type,
            "aliases": [x.strip() for x in (aliases or "").split(",") if x.strip()],
            "confidence": confidence,
            "provenance": provenance,
        }

    by_name = _canonical_id(rows, db)
    evidence_map = {}
    try:
        evidence_rows = db.execute("SELECT source_name,relation,target_name,evidence_document_id,status FROM relation_evidence")
    except Exception as exc:
        if "no such table" in str(exc):
            evidence_rows = []
        else:
            raise
    for source_name, relation, target_name, evidence_id, status in evidence_rows:
        evidence_map.setdefault((source_name, relation, target_name), []).append({
            "document_id": evidence_id,
            "status": status,
        })

    relation_provenance = {}
    try:
        for doc_id, source_name, relation, target_name in db.execute("SELECT document_id,source_name,relation,target_name FROM document_relations ORDER BY document_id"):
            relation_provenance.setdefault((source_name, relation, target_name), []).append({"document_id": doc_id})
    except Exception as exc:
        if "no such table" not in str(exc):
            raise

    edges = []
    seen = set()
    for source, relation, target, confidence in db.execute(
        "SELECT source_name,relation,target_name,confidence FROM relations"
    ):
        source_ids = by_name.get(source, [])
        target_ids = by_name.get(target, [])
        if len(source_ids) != 1 or len(target_ids) != 1:
            continue
        edge = {
            "source": source_ids[0],
            "relation": relation,
            "target": target_ids[0],
            "confidence": confidence,
        }
        provenance = relation_provenance.get((source, relation, target), [])
        if provenance:
            edge["provenance"] = provenance
        evidence = evidence_map.get((source, relation, target), [])
        if evidence:
            edge["evidence"] = evidence
        key = (edge["source"], relation, edge["target"])
        if key not in seen:
            seen.add(key)
            edges.append(edge)

    try:
        derived_rows = db.execute(
            "SELECT source_name,relation,target_name,confidence,rule,provenance FROM derived_relations"
        )
    except Exception as exc:
        if "no such table" in str(exc):
            derived_rows = []
        else:
            raise
    for source, relation, target, confidence, rule, provenance in derived_rows:
        source_ids = by_name.get(source, [])
        target_ids = by_name.get(target, [])
        if len(source_ids) != 1 or len(target_ids) != 1:
            continue
        key = (source_ids[0], relation, target_ids[0], "derived")
        if key in seen:
            continue
        edge = {
            "source": source_ids[0],
            "relation": relation,
            "target": target_ids[0],
            "confidence": confidence,
            "kind": "derived",
            "rule": rule,
            "provenance": json.loads(provenance),
        }
        seen.add(key)
        edges.append(edge)

    # Export deterministic cross-domain links as first-class graph edges.
    try:
        vocab_rows = db.execute(
            "SELECT id,word,traditional,pinyin,source FROM vocabularies ORDER BY id"
        ).fetchall()
    except Exception as exc:
        if "no such table" in str(exc):
            vocab_rows = []
        else:
            raise
    for vocabulary_id, word, traditional, pinyin, source in vocab_rows:
        node_id = f"Vocabulary:{vocabulary_id}"
        nodes[node_id] = {
            "id": node_id,
            "name": word,
            "type": "Vocabulary",
            "vocabulary_id": vocabulary_id,
            "traditional": traditional or "",
            "pinyin": pinyin or "",
            "source": source,
        }

    try:
        cross_rows = db.execute(
            """SELECT left_name,left_type,right_id,right_kind,confidence,rule,provenance
                 FROM cross_domain_links
                ORDER BY left_name,right_kind,right_id"""
        ).fetchall()
    except Exception as exc:
        if "no such table" in str(exc):
            cross_rows = []
        else:
            raise
    for left_name, left_type, right_id, right_kind, confidence, rule, provenance in cross_rows:
        if right_kind == "vocabulary":
            source_id = by_name.get(left_name, [])
            target_id = f"Vocabulary:{right_id}"
            if len(source_id) != 1 or target_id not in nodes:
                continue
            source_id = source_id[0]
        elif left_type == "Vocabulary":
            source_id = f"Vocabulary:{left_name}"
            target_id = by_name.get(right_id, [])
            if source_id not in nodes or len(target_id) != 1:
                continue
            target_id = target_id[0]
        else:
            continue
        key = (source_id, "cross_domain", target_id, "cross_domain")
        if key in seen:
            continue
        edge = {
            "source": source_id,
            "relation": "cross_domain",
            "target": target_id,
            "confidence": confidence,
            "kind": "cross_domain",
            "rule": rule,
            "provenance": json.loads(provenance),
        }
        seen.add(key)
        edges.append(edge)

    payload = {
        "schema_version": "6",
        "nodes": list(nodes.values()),
        "edges": edges,
    }
    out = Path(root) / "graph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
