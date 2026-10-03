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
    for alias, canonical_name, entity_type in db.execute(
        "SELECT alias,canonical_name,entity_type FROM entity_aliases"
    ):
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
        nodes[node_id] = {
            "id": node_id,
            "name": name,
            "type": entity_type,
            "aliases": [x.strip() for x in (aliases or "").split(",") if x.strip()],
            "confidence": confidence,
        }

    by_name = _canonical_id(rows, db)
    evidence_map = {}
    for source_name, relation, target_name, evidence_id, status in db.execute(
        "SELECT source_name,relation,target_name,evidence_document_id,status "
        "FROM relation_evidence"
    ):
        evidence_map.setdefault((source_name, relation, target_name), []).append({
            "document_id": evidence_id,
            "status": status,
        })

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
        evidence = evidence_map.get((source, relation, target), [])
        if evidence:
            edge["evidence"] = evidence
        key = (edge["source"], relation, edge["target"])
        if key not in seen:
            seen.add(key)
            edges.append(edge)

    payload = {
        "schema_version": "2",
        "nodes": list(nodes.values()),
        "edges": edges,
    }
    out = Path(root) / "graph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
