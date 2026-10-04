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
