import json
from .db import connect


def derive_source_bridge_links(db=None):
    """Link canonical entities across source domains using provenance only.

    No semantic guessing is performed. A bridge exists only when the same
    canonical (name, type) entity has concrete entity_sources rows from two
    distinct sources. Provenance retains the supporting document IDs per source.
    """
    own = db is None
    db = db or connect()
    db.execute(
        """CREATE TABLE IF NOT EXISTS source_bridge_links(
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            source_a TEXT NOT NULL,
            source_b TEXT NOT NULL,
            confidence REAL NOT NULL,
            rule TEXT NOT NULL,
            provenance TEXT NOT NULL,
            PRIMARY KEY(entity_name,entity_type,source_a,source_b,rule)
        )"""
    )
    db.execute("DELETE FROM source_bridge_links")

    try:
        rows = db.execute(
            """SELECT entity_name,entity_type,source,
                      GROUP_CONCAT(document_id, '|')
                 FROM entity_sources
                GROUP BY entity_name,entity_type,source
                ORDER BY entity_name,entity_type,source"""
        ).fetchall()
    except Exception as exc:
        if "no such table" in str(exc):
            rows = []
        else:
            raise

    grouped = {}
    for name, etype, source, docs in rows:
        grouped.setdefault((name, etype), {})[source] = sorted(
            x for x in (docs or "").split("|") if x
        )

    count = 0
    for (name, etype), sources in grouped.items():
        source_names = sorted(sources)
        if len(source_names) < 2:
            continue
        for i, source_a in enumerate(source_names):
            for source_b in source_names[i + 1:]:
                provenance = {
                    "entity": {"name": name, "type": etype},
                    "sources": {
                        source_a: {"document_ids": sources[source_a]},
                        source_b: {"document_ids": sources[source_b]},
                    },
                }
                db.execute(
                    """INSERT OR REPLACE INTO source_bridge_links
                       (entity_name,entity_type,source_a,source_b,confidence,rule,provenance)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        name, etype, source_a, source_b, 1.0,
                        "shared_canonical_entity",
                        json.dumps(provenance, ensure_ascii=False),
                    ),
                )
                count += 1

    if own:
        db.commit()
        db.close()
    return count


def augment_graph_with_source_bridges(root):
    """Add source-bridge edges to an existing graph.json without changing raw edges."""
    from pathlib import Path

    path = Path(root) / "graph.json"
    if not path.exists():
        return 0

    db = connect()
    try:
        try:
            rows = db.execute(
                """SELECT entity_name,entity_type,source_a,source_b,
                          confidence,rule,provenance
                     FROM source_bridge_links
                    ORDER BY entity_name,entity_type,source_a,source_b"""
            ).fetchall()
        except Exception as exc:
            if "no such table" in str(exc):
                rows = []
            else:
                raise
    finally:
        db.close()

    payload = json.loads(path.read_text(encoding="utf-8"))
    edges = payload.setdefault("edges", [])
    seen = {
        (e.get("source"), e.get("relation"), e.get("target"), e.get("kind"))
        for e in edges
    }

    added = 0
    for name, etype, source_a, source_b, confidence, rule, provenance in rows:
        node_id = f"{etype}:{name}"
        key = (node_id, "source_bridge", f"Source:{source_a}↔{source_b}", "source_bridge")
        if key in seen:
            continue
        edges.append({
            "source": node_id,
            "relation": "source_bridge",
            "target": f"Source:{source_a}↔{source_b}",
            "confidence": confidence,
            "kind": "source_bridge",
            "rule": rule,
            "provenance": json.loads(provenance),
        })
        seen.add(key)
        added += 1

    payload["schema_version"] = "7"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return added
