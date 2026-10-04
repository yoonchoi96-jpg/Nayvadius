# Nayvadius

Personal knowledge graph and cross-source verification engine.

## Core boundary

- **Abraham:** Readwise/Reader collection, selection, rating, translation, entity/relation extraction, and knowledge admission.
- **Nayvadius:** canonicalization, deduplication, cross-document linking, graph construction, provenance, and downstream knowledge structure.
- **Readwise:** remains an on-demand evidence/source layer for verification; Nayvadius does not ingest or classify the Reader library directly.
- **Obsidian / Notion:** downstream knowledge interfaces.

```
Readwise Reader
      ↓
   ABRAHAM
      ↓ enriched JSONL
  NAYVADIUS
      ├── canonical entities
      ├── relations / graph
      ├── deduplication
      ├── provenance
      └── source verification → Readwise (on demand)
             ↓
       Obsidian / Notion
```

## Input contract

Nayvadius accepts an Abraham export record such as:

```json
{
  "id": "reader-document-id",
  "title": "Example",
  "content": "Original document text",
  "source": "readwise",
  "metadata": {
    "readwise_id": "reader-document-id",
    "url": "https://example.com"
  },
  "rating": "red",
  "tags": ["topic/example"],
  "translation_ko": "한국어 번역",
  "entities": [
    {"name": "Example Entity", "entity_type": "Concepts", "confidence": 0.95}
  ],
  "relations": [
    {"source": "Example Entity", "relation": "related_to", "target": "Another Entity", "confidence": 0.9}
  ]
}
```

Abraham's extracted knowledge is persisted directly; Nayvadius does not spend an LLM call re-extracting it.

## Verification

`ReadwiseEvidenceClient` performs a targeted Reader API lookup by document ID only when source evidence is needed. The official Reader API supports filtering the document list by `id`.

## Runtime principles

- No self-hosted runner.
- GitHub-hosted Actions only.
- Incremental processing.
- Provider-agnostic optional AI layer.
- SQLite state/cache.
- Obsidian output first; other destinations can be added later.
- Cloud infrastructure is optional until actual workload requires it.


## Abraham export handoff

Recommended path:

`data/abraham_export.jsonl`

One JSON object per line. Abraham remains responsible for Readwise/Reader collection, rating, translation, entities, and relations. Nayvadius consumes the enriched records without re-running extraction.

Required fields:
- `id`
- `content`

Recommended fields:
- `title`
- `source`
- `metadata.readwise_id`
- `tags`
- `translation_ko`
- `entities`
- `relations`
- `related_ids`
- `importance`
- `document_type`

Processing is incremental by document content hash. Workflow batches can use `offset` and `limit` when a large Abraham export is introduced.


## Abel integration

Abel is a separate vocabulary source. It remains responsible for Naver Dictionary collection and HSK curation; Nayvadius integrates the resulting vocabulary into the canonical knowledge graph.

Supported Abel inputs:
- CSV exports such as `hsk30_level6_1140.csv`
- JSONL exports with richer metadata

Canonical vocabulary is stored separately from entities:

`vocabularies → entity_vocabulary_links → canonical entities`

This preserves Abel provenance instead of overwriting Abraham knowledge. Exact Chinese word/traditional-form matches are linked automatically; Abraham/Abel can also provide explicit entity names through `metadata.entities`.

The dedicated GitHub Actions workflow is:

`.github/workflows/abel.yml`

Recommended handoff paths:
- `data/abel_export.csv`
- `data/abel_export.jsonl`

The resulting vocabulary notes are written to `output/vocabulary/`, while canonical entity notes remain under `output/entities/`.

### Multi-source principle

Abraham answers **what should become knowledge**. Abel supplies **language/vocabulary evidence**. Nayvadius answers **how those records connect to the same canonical knowledge graph**.

Neither source is allowed to silently overwrite the other source's provenance.
