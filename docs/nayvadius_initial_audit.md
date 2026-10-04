# NAYVADIUS INITIAL AUDIT

This audit describes the checked-in repository and sample `output/` directory. No external Obsidian vault or live vault path is configured here, so existing personal notes and manual edits cannot be inspected.

## Repository architecture

The Python package is under `src/nayvadius/`. `Engine` coordinates adapters, persistence, graph derivation, quality checks, and output. SQLite is the state store; `output/` contains generated Markdown and JSON examples. There is no Obsidian plugin or bidirectional vault sync.

### Database schema

The idempotent schema is declared in `src/nayvadius/db.py`; `connect()` enables WAL and foreign keys and applies compatibility migrations.

- Documents and processing: `documents`, `results`, `llm_cache`, `processing_failures`.
- Canonical graph: `entities`, `entity_aliases`, `relations`, `document_entities`, `document_relations`.
- Provenance and evidence: `entity_sources`, `evidence`, `relation_evidence`.
- Merge history: `entity_merge_log`.
- Abel vocabulary: `vocabularies`, `vocabulary_aliases`, `vocabulary_sources`, `entity_vocabulary_links`, `document_vocabulary_links`.
- Derived graph tables are initialized by inference modules: `derived_relations`, `cross_domain_links`, and `source_bridge_links`.

`entities` is the canonical entity store; `entity_aliases` is the normalized alias map and `entity_merge_log` is the merge audit trail. These are the repository's existing equivalents of a separately named `canonical_entities`, `aliases`, and `entity_merges` schema. Merge rewiring is same-type only, rejects self-merges, and preserves the strongest confidence. The legacy Companies/Brands migration maps both to Organizations. Abraham document text is now retained to allow later vocabulary batches to relink already-ingested documents; pre-migration rows retain an empty content value and need upstream reprocessing to be backfilled.

The database is not fully relationally constrained: most endpoint integrity is enforced by application logic and the QA pass, rather than SQLite foreign keys.

### Entity and relation handling

The canonical ontology in `src/nayvadius/qa.py` has People, Organizations, Countries, Places, Products, Technologies, Concepts, Events, Institutions, MusicTracks, and MusicAlbums. Alias lookup normalizes case and whitespace and only canonicalizes an unambiguous same-type match. Conflicting aliases are retained as QA warnings; they are not automatically merged.

Raw relations live in `relations` and document attribution in `document_relations`. Evidence is separately tracked in `evidence` and `relation_evidence`. `inference.py` derives the deterministic `performed` + `part_of` → `contributed_to` chain without overwriting raw relations. Inference and bridge logic is currently a small set of explicit rules, not a general-purpose transitive reasoner.

### Source integration and provenance

`config/integrations.json` defines upstream ownership and handoff contracts:

- Abraham sends enriched JSONL; Nayvadius consumes extracted entities and relations.
- Abel sends CSV/JSONL vocabulary; vocabulary provenance is retained separately from canonical entities.
- Jacques sends music JSON; tracks and albums are represented as canonical music entities.

Adapters are in `src/nayvadius/adapters.py`. Provenance is retained per source/document, and deterministic cross-domain/source bridges are derived from shared canonical entities and vocabulary matches. Source collection remains upstream; no live upstream API synchronization is configured.

### Knowledge graph and output

`graph.py` serializes canonical entities, raw/derived relations, cross-domain vocabulary links, evidence, and source bridges to `output/graph.json`. `writer.py` emits document and entity Markdown, vocabulary notes, entity/domain/knowledge/cross-domain MOCs, and indexes. `notion_export.py` writes a deterministic projection manifest; it does not call the Notion API.

The checked-in `output/` contains a small sample document, three example Concept notes, and a graph JSON file. It does not establish the structure or contents of a user's full vault.

## KNOWLEDGE GRAPH ARCHITECTURE

```text
Abraham JSONL ──> documents/results ──> entities ──> relations
                         │                 │               │
                         └── document provenance ──────────┘
Abel CSV/JSONL ──> vocabularies ── entity/document vocabulary links
Jacques JSON ────> music entities and relations
                         │
          source bridges + deterministic derived links
                         │
       graph.json + Obsidian Markdown/MOCs + Notion manifest
```

The database is the working canonical state, while upstream projects own their source records. Raw, derived, and evidence-backed relationships have distinct representations. The output layer is a downstream projection; there is no reverse write path to Abraham, Abel, or Jacques.

## QA, automation, and safety

`qa.py` is deterministic and API-free. It checks required tables, canonical entity types and confidence, alias collisions and dangling targets, document/entity and document/relation links, relation endpoints/names/confidence, evidence links/status, orphan results, merge self-links, and processing failures. Errors fail `nayvadius.cli qa`; warnings are reported without failing. The CI workflow runs unit tests, an end-to-end sample process, and this QA gate.

`.github/workflows/process.yml`, `abel.yml`, and `jacques.yml` handle the three exports. They support bounded batches or manual dispatch, serialize state writers with a concurrency group, and commit generated output and SQLite state. `process.yml` also retries failed Abraham documents.

Processing hashes inputs for incremental updates; graph derivation is deterministic and output files are atomically replaced. However, generated note paths are rewritten on subsequent runs. There are no generated-region markers, dry-run mode, rollback mechanism, or protection for human edits in generated files. Do not point these workflows at a manually curated vault until that overwrite policy is addressed.

## Verified gaps

- No live vault configuration, bidirectional sync, or human-edit preservation mechanism.
- No general ontology resolver or relation inference engine; canonicalization and inference use deterministic exact/alias rules.
- Older databases are upgraded in place without a versioned migration registry; legacy document rows cannot be vocabulary-reconciled until reprocessed from the upstream export.
- Notion support is a manifest only, and evidence verification is targeted rather than an automated relation-verification workflow.
- The repository provides no persistent import cursor beyond content hashes and caller-provided batch offset/limit.
