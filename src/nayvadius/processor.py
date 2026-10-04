import math,re
from .models import Document,Entity,Relation,ProcessedDocument

ENTITY_TYPES = {
    "People", "Organizations", "Countries", "Places",
    "Products", "Technologies", "Concepts", "Events", "Institutions", "MusicTracks", "MusicAlbums",
}
_ENTITY_TYPE_ALIASES = {
    "person": "People", "people": "People",
    "organization": "Organizations", "organizations": "Organizations",
    "company": "Organizations", "companies": "Organizations",
    "brand": "Organizations", "brands": "Organizations",
    "country": "Countries", "countries": "Countries",
    "place": "Places", "places": "Places",
    "product": "Products", "products": "Products",
    "technology": "Technologies", "technologies": "Technologies",
    "concept": "Concepts", "concepts": "Concepts",
    "event": "Events", "events": "Events",
    "institution": "Institutions", "institutions": "Institutions",
    "musictrack": "MusicTracks", "musictracks": "MusicTracks", "track": "MusicTracks", "tracks": "MusicTracks",
    "musicalbum": "MusicAlbums", "musicalbums": "MusicAlbums", "album": "MusicAlbums", "albums": "MusicAlbums",
}

RELATION_TYPES = {
    "owns", "owned_by", "operates", "operated_by", "brand_of",
    "subsidiary_of", "parent_of", "acquired", "acquired_by",
}

def normalize_relation_type(value):
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in RELATION_TYPES else str(value or "").strip()

def normalize_entity_type(value):
    key = str(value or "").strip().lower()
    return _ENTITY_TYPE_ALIASES.get(key, "Concepts")

def process_document(doc: Document) -> ProcessedDocument:
    words = doc.content.split()
    names = []
    for n in re.findall(r"\b[A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})*\b", doc.content):
        if n not in names:
            names.append(n)
    return ProcessedDocument(
        doc, " ".join(words[:120]),
        [Entity(n, "Concepts", 0.5) for n in names[:30]],
        [f"source/{doc.source}"], []
    )

def parse_llm(obj: dict, doc: Document) -> ProcessedDocument:
    if not isinstance(obj, dict):
        raise ValueError("LLM payload must be an object")

    def text(v, d=""):
        return v.strip() if isinstance(v, str) else d

    def confidence(v, d=1.0):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return d
        return max(0.0, min(1.0, x)) if math.isfinite(x) else d

    entities = []
    for raw in obj.get("entities", []) or []:
        if not isinstance(raw, dict):
            continue
        name = text(raw.get("name"))
        if not name:
            continue
        aliases = raw.get("aliases", []) or []
        if not isinstance(aliases, (list, tuple)):
            aliases = []
        clean_aliases = tuple(str(x).strip() for x in aliases if str(x).strip())
        entities.append(Entity(
            name,
            normalize_entity_type(raw.get("entity_type")),
            confidence(raw.get("confidence")),
            clean_aliases,
        ))

    relations = []
    for raw in obj.get("relations", []) or []:
        if not isinstance(raw, dict):
            continue
        source = text(raw.get("source"))
        target = text(raw.get("target"))
        relation = normalize_relation_type(raw.get("relation"))
        if source and target and relation:
            relations.append(Relation(source, relation, target, confidence(raw.get("confidence"))))

    raw_tags = obj.get("tags", []) or []
    raw_related = obj.get("related_ids", []) or []
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = []
    if not isinstance(raw_related, (list, tuple)):
        raw_related = []

    tags = [str(x).strip() for x in raw_tags if str(x).strip()]
    related = [str(x).strip() for x in raw_related if str(x).strip()]

    return ProcessedDocument(
        doc,
        text(obj.get("summary"), doc.content[:500]),
        entities,
        tags or [f"source/{doc.source}"],
        related,
        relations,
        confidence(obj.get("importance"), 0.5),
        text(obj.get("document_type"), "note"),
        text(obj.get("translation_ko")),
    )
