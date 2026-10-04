from nayvadius.adapters import parse_abel_record
from nayvadius.models import Vocabulary


def test_parse_abel_hsk_csv_shape():
    record = {
        "id": "L6-0001",
        "word": "挨着",
        "traditional": "挨著",
        "pinyin": "āizhe",
        "pos": "表达",
        "meaning_ko": "~에 붙어 있다",
    }
    value = parse_abel_record(record)
    assert isinstance(value, Vocabulary)
    assert value.word == "挨着"
    assert value.traditional == "挨著"
    assert value.pinyin == "āizhe"
    assert value.meaning_ko == "~에 붙어 있다"


def test_parse_abel_json_shape_preserves_memberships():
    value = parse_abel_record({
        "id": "x",
        "word": "经济",
        "hsk_levels": ["HSK6"],
        "wordbooks": ["HSK 6급", "경제"],
        "metadata": {"entities": ["经济"]},
    })
    assert value.hsk_levels == ("HSK6",)
    assert value.wordbooks == ("HSK 6급", "경제")
    assert value.metadata["entities"] == ["经济"]


def test_duplicate_headwords_merge_across_sources():
    from nayvadius.db import connect
    from nayvadius.models import Vocabulary
    from nayvadius.store import link_vocabulary

    a = Vocabulary(id="L6-0001", word="经济", hsk_levels=("HSK6",), wordbooks=("HSK 6급",), source="abel")
    b = Vocabulary(id="L7-0001", word="经济", traditional="經濟", hsk_levels=("HSK7",), wordbooks=("HSK 7-9급",), source="abel")
    link_vocabulary(a)
    link_vocabulary(b)
    with connect() as db:
        rows = db.execute("SELECT id,hsk_levels,wordbooks FROM vocabularies WHERE word='经济'").fetchall()
        assert len(rows) == 1
        assert "HSK6" in rows[0][1] and "HSK7" in rows[0][1]
        assert "HSK 6급" in rows[0][2] and "HSK 7-9급" in rows[0][2]


def test_abel_source_provenance_and_document_linking():
    from nayvadius.db import connect
    from nayvadius.models import Document
    from nayvadius.store import link_vocabulary, link_document_to_vocabularies

    value = Vocabulary(
        id="L6-0002",
        word="人工智能",
        traditional="人工智能",
        pinyin="rengong zhineng",
        hsk_levels=("HSK6",),
        source="abel",
        metadata={"wordbook": "HSK 6급"},
    )
    link_vocabulary(value)

    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO documents(id,title,content_hash,source,status) VALUES(?,?,?,?,?)",
            ("abraham-1", "AI", "hash", "readwise", "done"),
        )

    count = link_document_to_vocabularies("abraham-1", "人工智能正在改变产业。")
    assert count == 1

    with connect() as db:
        source = db.execute(
            "SELECT source_id,source FROM vocabulary_sources WHERE vocabulary_id=?",
            ("L6-0002",),
        ).fetchone()
        link = db.execute(
            "SELECT vocabulary_id,match_type FROM document_vocabulary_links WHERE document_id=?",
            ("abraham-1",),
        ).fetchone()
    assert source == ("L6-0002", "abel")
    assert link == ("L6-0002", "exact")
