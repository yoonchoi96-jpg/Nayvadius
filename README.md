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
