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
        provenance = json.dumps([{
            "source": artist,
            "relation": "performed",
            "target": track,
        }, {
            "source": track,
            "relation": "part_of",
            "target": album,
        }])
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
