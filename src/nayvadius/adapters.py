from abc import ABC, abstractmethod
import json

from .models import Document, Entity, Relation, ProcessedDocument, Vocabulary
from .processor import normalize_entity_type


class DocumentAdapter(ABC):
    @abstractmethod
    def load(self) -> list[Document]:
        raise NotImplementedError


class JsonlAdapter(DocumentAdapter):
    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[Document]:
        from .io import load_jsonl
        return load_jsonl(self.path)


def _clean_list(value):
    return value if isinstance(value, list) else []


def _entity(raw):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    aliases = tuple(str(x).strip() for x in _clean_list(raw.get("aliases")) if str(x).strip())
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 1.0))))
    except (TypeError, ValueError):
        confidence = 1.0
    return Entity(name, normalize_entity_type(raw.get("entity_type")), confidence, aliases)


def _relation(raw):
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or "").strip()
    relation = str(raw.get("relation") or "").strip()
    target = str(raw.get("target") or "").strip()
    if not source or not relation or not target:
        return None
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 1.0))))
    except (TypeError, ValueError):
        confidence = 1.0
    return Relation(source, relation, target, confidence)


def parse_abraham_document(raw: dict) -> ProcessedDocument:
    if not isinstance(raw, dict):
        raise ValueError("Abraham record must be an object")
    doc_id = str(raw.get("id") or "").strip()
    content = str(raw.get("content") or "").strip()
    if not doc_id or not content:
        raise ValueError("Abraham record requires id and non-empty content")

    doc = Document(
        doc_id,
        str(raw.get("title") or doc_id),
        content,
        str(raw.get("source") or "abraham"),
        raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )
    entities = [x for x in (_entity(v) for v in _clean_list(raw.get("entities"))) if x]
    relations = [x for x in (_relation(v) for v in _clean_list(raw.get("relations"))) if x]
    tags = [str(x).strip() for x in _clean_list(raw.get("tags")) if str(x).strip()]
    related = [str(x).strip() for x in _clean_list(raw.get("related_ids")) if str(x).strip()]
    try:
        importance = max(0.0, min(1.0, float(raw.get("importance", 0.5))))
    except (TypeError, ValueError):
        importance = 0.5

    return ProcessedDocument(
        doc,
        str(raw.get("summary") or content[:500]),
        entities,
        tags or [f"source/{doc.source}"],
        related,
        relations,
        importance,
        str(raw.get("document_type") or "note"),
        str(raw.get("translation_ko") or ""),
    )


def load_abraham_jsonl(path: str) -> list[ProcessedDocument]:
    records = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(parse_abraham_document(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid Abraham input line {line_no}: {exc}") from exc
    return records



def _csv_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_abel_record(raw: dict) -> Vocabulary:
    if not isinstance(raw, dict):
        raise ValueError("Abel record must be an object")
    word = _csv_value(raw, "word", "simplified", "词")
    if not word:
        raise ValueError("Abel record requires word")
    vid = _csv_value(raw, "id", "word_id") or word
    levels = raw.get("hsk_levels", raw.get("hsk_level", []))
    books = raw.get("wordbooks", raw.get("wordbook", []))
    if not isinstance(levels, list):
        levels = [levels] if levels else []
    if not isinstance(books, list):
        books = [books] if books else []
    levels = tuple(str(x).strip() for x in levels if str(x).strip())
    books = tuple(str(x).strip() for x in books if str(x).strip())
    return Vocabulary(
        id=vid,
        word=word,
        traditional=_csv_value(raw, "traditional", "繁体"),
        pinyin=_csv_value(raw, "pinyin", "拼音"),
        pos=_csv_value(raw, "pos", "part_of_speech"),
        meaning_ko=_csv_value(raw, "meaning_ko", "meaning", "definition_ko"),
        hsk_levels=levels,
        wordbooks=books,
        source=str(raw.get("source") or "abel"),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )


def load_abel_csv(path: str) -> list[Vocabulary]:
    import csv
    records = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            records.append(parse_abel_record(row))
    return records


def load_abel_jsonl(path: str) -> list[Vocabulary]:
    records = []
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(parse_abel_record(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid Abel input line {line_no}: {exc}") from exc
    return records


def load_abel(path: str) -> list[Vocabulary]:
    return load_abel_csv(path) if path.lower().endswith(".csv") else load_abel_jsonl(path)


def load_documents(adapter: DocumentAdapter) -> list[Document]:
    return adapter.load()


def parse_jacques_track(raw: dict) -> ProcessedDocument:
    if not isinstance(raw, dict):
        raise ValueError("Jacques track must be an object")
    track_id = str(raw.get("track_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not track_id or not title:
        raise ValueError("Jacques track requires track_id and title")
    artists = [x.strip() for x in str(raw.get("artists") or "").split(",") if x.strip()]
    album = str(raw.get("album") or "").strip()
    content_parts = [
        f"Track: {title}",
        f"Artists: {', '.join(artists)}" if artists else "",
        f"Album: {album}" if album else "",
        f"Release date: {raw.get('release_date') or ''}",
        f"Spotify URL: {raw.get('spotify_url') or ''}",
    ]
    for key in ("audio_features", "enrichment", "analysis", "editorial"):
        value = raw.get(key)
        if value not in (None, "", [], {}):
            content_parts.append(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    content = "\n".join(x for x in content_parts if x)
    entities = []
    for artist in artists:
        entities.append(Entity(artist, "People", 1.0, ()))
    if album:
        entities.append(Entity(album, "MusicAlbums", 1.0, ()))
    entities.append(Entity(title, "MusicTracks", 1.0, ()))
    relations = [Relation(artist, "performed", title, 1.0) for artist in artists]
    if album:
        relations.append(Relation(title, "part_of", album, 1.0))
    metadata = {
        "jacques": {k: v for k, v in raw.items() if k not in {"track_id", "title", "artists", "album", "release_date", "spotify_url"}}
    }
    metadata["source_id"] = track_id
    metadata["source"] = "jacques"
    doc = Document(track_id, title, content, "jacques", metadata)
    return ProcessedDocument(
        doc,
        f"{title} — {', '.join(artists)}" if artists else title,
        entities,
        ["source/jacques", "domain/music"],
        [],
        relations,
        0.5,
        "music_track",
        "",
    )


def load_jacques_json(path: str) -> list[ProcessedDocument]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    tracks = payload.get("tracks", []) if isinstance(payload, dict) else payload
    if not isinstance(tracks, list):
        raise ValueError("Jacques JSON requires a tracks list")
    return [parse_jacques_track(track) for track in tracks]
