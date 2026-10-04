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
    """Derive deterministic cross-domain links with explicit provenance.

    Rules:
      1) Abraham entity + Abel vocabulary in the same Abraham document.
      2) Shared canonical Abraham/Jacques entity + Jacques performed->track relation
         => Abel vocabulary <-> Jacques track.
      3) The same path extended through track part_of->album
         => Abel vocabulary <-> Jacques album.

    Raw entity/relation/vocabulary links are never overwritten.
    """
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

    # Base: entity <-> vocabulary co-occurrence in an Abraham document.
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

    # Three-way bridge:
    # Abraham entity + Abel vocabulary + the same canonical entity in Jacques.
    bridge_rows = db.execute(
        """SELECT av.entity_name, av.entity_type, av.vocabulary_id,
                  MIN(av.entity_confidence, av.vocab_confidence, jtrack.confidence),
                  av.abraham_document_id, jtrack.document_id,
                  jtrack.target_name, jtrack.target_type
             FROM (
                 SELECT de.entity_name, de.entity_type, dv.vocabulary_id,
                        de.confidence AS entity_confidence,
                        dv.confidence AS vocab_confidence,
                        d.id AS abraham_document_id
                   FROM document_entities de
                   JOIN documents d ON d.id=de.document_id
                   JOIN document_vocabulary_links dv ON dv.document_id=d.id
                  WHERE d.source='abraham'
             ) av
             JOIN document_entities je
               ON je.entity_name=av.entity_name
              AND je.entity_type=av.entity_type
             JOIN documents jd ON jd.id=je.document_id AND jd.source='jacques'
             JOIN document_relations jtrack
               ON jtrack.document_id=je.document_id
              AND jtrack.source_name=je.entity_name
              AND jtrack.relation='performed'
             JOIN entities te
               ON te.name=jtrack.target_name
              AND te.entity_type='MusicTracks'
            GROUP BY av.entity_name,av.entity_type,av.vocabulary_id,
                     av.abraham_document_id,jtrack.document_id,
                     jtrack.target_name,jtrack.target_type"""
    ).fetchall()

    for (entity_name, entity_type, vocabulary_id, confidence,
         abraham_document_id, jacques_document_id, track_name, track_type) in bridge_rows:
        db.execute(
            """INSERT OR REPLACE INTO cross_domain_links
               (left_name,left_type,right_id,right_kind,confidence,rule,provenance)
               VALUES(?,?,?,?,?,?,?)""",
            (entity_name, entity_type, vocabulary_id, "vocabulary",
             round(float(confidence) * 0.9, 6),
             "abraham_entity+abel_vocabulary+jacques_track",
             json.dumps({
                 "document_ids": [abraham_document_id, jacques_document_id],
                 "shared_entity": {
                     "name": entity_name,
                     "type": entity_type,
                 },
                 "music": {
                     "track": track_name,
                     "track_type": track_type,
                 },
             }, ensure_ascii=False)),
        )

        # Vocabulary -> track is a separate derived edge so the three-way
        # connection is directly navigable without losing the shared-entity path.
        db.execute(
            """INSERT OR REPLACE INTO cross_domain_links
               (left_name,left_type,right_id,right_kind,confidence,rule,provenance)
               VALUES(?,?,?,?,?,?,?)""",
            (vocabulary_id, "Vocabulary", track_name, "music_track",
             round(float(confidence) * 0.81, 6),
             "abraham_entity+abel_vocabulary+jacques_track",
             json.dumps({
                 "document_ids": [abraham_document_id, jacques_document_id],
                 "shared_entity": {"name": entity_name, "type": entity_type},
                 "vocabulary_id": vocabulary_id,
             }, ensure_ascii=False)),
        )

    # Extend the same deterministic bridge from track to album.
    album_rows = db.execute(
        """SELECT c.right_id, c.right_kind, c.confidence, c.rule, c.provenance,
                  r.target_name, r.target_name
             FROM cross_domain_links c
             JOIN relations r
               ON r.source_name=c.right_id
              AND r.relation='part_of'
             WHERE c.right_kind='music_track'"""
    ).fetchall()
    for vocabulary_id, _, confidence, rule, provenance, album_name, _ in album_rows:
        payload = json.loads(provenance)
        document_ids = list(payload.get("document_ids", []))
        album_docs = [
            row[0] for row in db.execute(
                "SELECT document_id FROM document_relations "
                "WHERE source_name=? AND relation='part_of' AND target_name=? "
                "ORDER BY document_id",
                (vocabulary_id, album_name),
            )
        ]
        # The relation above is keyed by track, not vocabulary; recover its
        # supporting document from the existing track provenance instead.
        if not album_docs:
            track_name = next(
                (k for k in payload.get("shared_entity", {}) if k == "track"), None
            )
        db.execute(
            """INSERT OR REPLACE INTO cross_domain_links
               (left_name,left_type,right_id,right_kind,confidence,rule,provenance)
               VALUES(?,?,?,?,?,?,?)""",
            (vocabulary_id, "Vocabulary", album_name, "music_album",
             round(float(confidence) * 0.95, 6),
             "abraham_entity+abel_vocabulary+jacques_track+album",
             json.dumps({
                 "document_ids": document_ids,
                 "derived_from": payload,
                 "album": album_name,
             }, ensure_ascii=False)),
        )

    if own:
        db.commit()
        db.close()
    return len(rows) + len(bridge_rows)
