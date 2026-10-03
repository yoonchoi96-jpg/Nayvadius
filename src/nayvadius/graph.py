import json
from pathlib import Path

def _canonical_id(rows):
    by_name = {}
    for name, entity_type, aliases, confidence in rows:
        node_id = f"{entity_type}:{name}"
        by_name.setdefault(name, []).append(node_id)
        for alias in (aliases or "").split(","):
            alias = alias.strip()
            if alias:
                by_name.setdefault(alias, []).append(node_id)
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

    by_name = _canonical_id(rows)
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
        key = (edge["source"], relation, edge["target"])
        if key not in seen:
            seen.add(key)
            edges.append(edge)

    payload = {
        "schema_version": "1",
        "nodes": list(nodes.values()),
        "edges": edges,
    }
    out = Path(root) / "graph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
