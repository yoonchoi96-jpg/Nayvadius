import json
from pathlib import Path

def write_graph(db, root):
    nodes = {}
    for name, entity_type, aliases, confidence in db.execute(
        "SELECT name,entity_type,aliases,confidence FROM entities"
    ):
        nodes[f"{entity_type}:{name}"] = {
            "id": f"{entity_type}:{name}",
            "name": name,
            "type": entity_type,
            "aliases": [x for x in (aliases or "").split(",") if x],
            "confidence": confidence,
        }

    edges = []
    for source, relation, target, confidence in db.execute(
        "SELECT source_name,relation,target_name,confidence FROM relations"
    ):
        edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            "confidence": confidence,
        })

    payload = {"nodes": list(nodes.values()), "edges": edges}
    out = Path(root) / "graph.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
