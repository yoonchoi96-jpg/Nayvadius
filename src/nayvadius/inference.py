import json
from .db import connect


def derive_relation_chains(db=None):
    """Create only deterministic, provenance-preserving derived relations.

    Current rule:
      artist --performed--> track --part_of--> album
        => artist --contributed_to--> album

    Derived facts live separately from raw relations and can never overwrite them.
    """
    own = db is None
    db = db or connect()
    db.execute(
        """CREATE TABLE IF NOT EXISTS derived_relations(
            source_name TEXT NOT NULL,
            relation TEXT NOT NULL,
            target_name TEXT NOT NULL,
            confidence REAL NOT NULL,
            rule TEXT NOT NULL,
            provenance TEXT NOT NULL,
            PRIMARY KEY(source_name,relation,target_name,rule)
        )"""
    )
    db.execute("DELETE FROM derived_relations")
    rows = db.execute(
        """SELECT r1.source_name, r1.target_name, r1.confidence,
                  r2.target_name, r2.confidence
           FROM relations r1
           JOIN relations r2
             ON r1.target_name = r2.source_name
          WHERE r1.relation='performed'
            AND r2.relation='part_of'"""
    ).fetchall()
    count = 0
    for artist, track, c1, album, c2 in rows:
        confidence = round(min(float(c1), float(c2)) * 0.95, 6)

        def relation_provenance(source, relation, target):
            try:
                docs = [
                    row[0]
                    for row in db.execute(
                        "SELECT document_id FROM document_relations "
                        "WHERE source_name=? AND relation=? AND target_name=? "
                        "ORDER BY document_id",
                        (source, relation, target),
                    )
                ]
            except Exception as exc:
                if "no such table" in str(exc):
                    docs = []
                else:
                    raise
            item = {
                "source": source,
                "relation": relation,
                "target": target,
            }
            if docs:
                item["document_ids"] = docs
            return item

        provenance = json.dumps([
            relation_provenance(artist, "performed", track),
            relation_provenance(track, "part_of", album),
        ], ensure_ascii=False)
        db.execute(
            """INSERT OR REPLACE INTO derived_relations
               (source_name,relation,target_name,confidence,rule,provenance)
               VALUES(?,?,?,?,?,?)""",
            (artist, "contributed_to", album, confidence,
             "performed+part_of", provenance),
        )
        count += 1
    if own:
        db.commit()
        db.close()
    return count


def derive_cross_domain_links(db=None):
    """Derive deterministic entity-vocabulary links from shared Abraham documents."""
    own = db is None
    db = db or connect()
    db.execute(
        """CREATE TABLE IF NOT EXISTS cross_domain_links(
            left_name TEXT NOT NULL,
            left_type TEXT NOT NULL,
            right_id TEXT NOT NULL,
            right_kind TEXT NOT NULL,
            confidence REAL NOT NULL,
            rule TEXT NOT NULL,
            provenance TEXT NOT NULL,
            PRIMARY KEY(left_name,left_type,right_id,right_kind,rule)
        )"""
    )
    db.execute("DELETE FROM cross_domain_links")
    rows = db.execute(
        """SELECT de.entity_name, de.entity_type, dv.vocabulary_id,
                  MIN(de.confidence, dv.confidence), d.id
             FROM document_entities de
             JOIN documents d ON d.id=de.document_id
             JOIN document_vocabulary_links dv ON dv.document_id=d.id
            WHERE d.source='abraham'
            GROUP BY de.entity_name,de.entity_type,dv.vocabulary_id,d.id"""
    ).fetchall()
    for entity_name, entity_type, vocabulary_id, confidence, document_id in rows:
        db.execute(
            """INSERT OR REPLACE INTO cross_domain_links
               (left_name,left_type,right_id,right_kind,confidence,rule,provenance)
               VALUES(?,?,?,?,?,?,?)""",
            (entity_name, entity_type, vocabulary_id, "vocabulary",
             round(float(confidence) * 0.9, 6),
             "same_abraham_document",
             json.dumps({"document_ids": [document_id]}, ensure_ascii=False)),
        )
    if own:
        db.commit()
        db.close()
    return len(rows)
