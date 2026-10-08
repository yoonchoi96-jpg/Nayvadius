import json
from pathlib import Path

from nayvadius.adapters import load_abraham_jsonl


def test_load_abraham_jsonl_preserves_enrichment(tmp_path: Path):
    p = tmp_path / "abraham.jsonl"
    p.write_text(json.dumps({
        "id": "rw-1",
        "title": "Example",
        "content": "Original",
        "source": "readwise",
        "metadata": {"readwise_id": "rw-1"},
        "tags": ["topic/test"],
        "translation_ko": "원문",
        "entities": [
            {"name": "Apple", "entity_type": "company", "confidence": 0.9}
        ],
        "relations": [
            {"source": "Apple", "relation": "related_to", "target": "Example"}
        ],
    }) + "\n", encoding="utf-8")

    records = load_abraham_jsonl(str(p))
    result = records[0]

    assert result.document.id == "rw-1"
    assert result.entities[0].entity_type == "Organizations"
    assert result.relations[0].source == "Apple"
    assert result.translation_ko == "원문"
    assert result.document.metadata["readwise_id"] == "rw-1"


def test_load_jacques_json_creates_music_graph(tmp_path: Path):
    from nayvadius.adapters import load_jacques_json
    p = tmp_path / "jacques.json"
    p.write_text(json.dumps({
        "tracks": [{
            "track_id": "track-1",
            "title": "Example Song",
            "artists": "Artist A, Artist B",
            "album": "Example Album",
            "release_date": "2026-01-01",
            "spotify_url": "https://open.spotify.com/track/track-1",
            "analysis": {"bpm": 100}
        }]
    }, ensure_ascii=False), encoding="utf-8")
    result = load_jacques_json(str(p))[0]
    assert result.document.source == "jacques"
    assert {e.name for e in result.entities} == {"Artist A", "Artist B", "Example Album", "Example Song"}
    assert {e.entity_type for e in result.entities if e.name == "Example Album"} == {"MusicAlbums"}
    assert {e.entity_type for e in result.entities if e.name == "Example Song"} == {"MusicTracks"}
    assert ("Artist A", "performed", "Example Song") == (
        result.relations[0].source, result.relations[0].relation, result.relations[0].target
    )
    assert "analysis" in result.document.content


def test_jacques_record_keeps_source_provenance():
    from nayvadius.adapters import parse_jacques_track
    result = parse_jacques_track({
        "track_id": "track-provenance",
        "title": "Provenance Song",
        "artists": "Artist",
        "album": "Album",
        "analysis": {"bpm": 120},
    })
    assert result.document.source == "jacques"
    assert result.document.id == "track-provenance"
    assert result.document.metadata["jacques"]["analysis"]["bpm"] == 120


def test_jacques_record_exposes_source_identity():
    from nayvadius.adapters import parse_jacques_track
    result = parse_jacques_track({
        "track_id": "track-source-id",
        "title": "Source Identity",
        "artists": "Artist",
    })
    assert result.document.metadata["source"] == "jacques"
    assert result.document.metadata["source_id"] == "track-source-id"


def test_abraham_record_exposes_source_identity():
    from nayvadius.adapters import parse_abraham_document
    result = parse_abraham_document({
        "id": "abraham-1",
        "title": "Source Contract",
        "content": "body",
        "source": "abraham",
    })
    assert result.document.metadata["source"] == "abraham"
    assert result.document.metadata["source_id"] == "abraham-1"


def test_abel_record_exposes_source_identity():
    from nayvadius.adapters import parse_abel_record
    result = parse_abel_record({
        "id": "abel-1",
        "word": "维护",
        "source": "abel",
    })
    assert result.metadata["source"] == "abel"
    assert result.metadata["source_id"] == "abel-1"
