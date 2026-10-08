from nayvadius.db import connect
from nayvadius.source_bridges import derive_source_bridge_links


def test_refresh_source_bridges_uses_only_shared_canonical_provenance(tmp_path):
    db = connect(tmp_path / "test.db")
    db.executemany(
        "INSERT INTO entity_sources VALUES(?,?,?,?)",
        [
            ("Shared", "Organizations", "abraham", "a1"),
            ("Shared", "Organizations", "jacques", "j1"),
            ("OnlyAbel", "Concepts", "abel", "v1"),
        ],
    )
    count = derive_source_bridge_links(db)
    rows = db.execute(
        "SELECT entity_name, source_a, source_b FROM source_bridge_links"
    ).fetchall()
    db.close()

    assert count == 1
    assert rows == [("Shared", "abraham", "jacques")]
