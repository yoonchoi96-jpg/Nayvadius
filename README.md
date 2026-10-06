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

## Canonical entity ontology

The canonical entity domains are:

- People
- Organizations
- Countries
- Places
- Products
- Technologies
- Concepts
- Events
- Institutions
- MusicTracks
- MusicAlbums

Companies and brands are intentionally unified under **Organizations**. Their distinction is represented through explicit relations such as `brand_of`, `owns`, `operates`, `subsidiary_of`, `parent_of`, `acquired`, and `acquired_by`.

Entity merges are conservative: they stay within the same canonical type and require an explicit or evidence-backed merge reason. Merge decisions are retained in the entity merge audit log.



## Deterministic second-stage QA

Nayvadius runs an API-free QA pass over its persisted SQLite state before knowledge
changes are committed:

```bash
python -m nayvadius.cli qa --db data/nayvadius.db --output output
```

The QA gate checks:

- canonical entity ontology and confidence ranges
- ambiguous alias collisions (warning; never auto-merged)
- orphan entity/source, vocabulary/source, and cross-domain links
- derived relation and source-bridge endpoints
- vocabulary-link and derived-graph confidence ranges
- orphan document/entity and document/relation links
- relation endpoint existence, naming, self-loops, and confidence
- relation-evidence provenance and evidence status
- orphan processing results
- invalid/self entity merge audit records
- persistent processing failures as warnings

Errors fail CI. Warnings are retained for later semantic review and do not consume
an LLM/API call. The resulting machine-readable report is written to
`output/qa_report.json`.

This is deliberately separate from Abraham's first-stage structural QA:
Abraham validates ingestion/extraction state; Nayvadius validates the integrity
and downstream consistency of the canonical knowledge graph.

## Architecture audit

See [NAYVADIUS INITIAL AUDIT](docs/nayvadius_initial_audit.md) for the repository-grounded schema, processing, graph, output, workflow, and gap inventory.

## Obsidian maintenance

Vault maintenance is read-only by default:

```bash
python -m nayvadius.cli obsidian-audit --output /path/to/vault --db data/nayvadius.db
python -m nayvadius.cli obsidian-normalize --output /path/to/vault
python -m nayvadius.cli obsidian-normalize --output /path/to/vault --apply
python -m nayvadius.cli entity-merge-plan --output /path/to/vault
python -m nayvadius.cli entity-merge-apply --output /path/to/vault --db data/nayvadius.db
python -m nayvadius.cli entity-merge-apply --output /path/to/vault --db data/nayvadius.db --apply
python -m nayvadius.cli maintenance --output /path/to/vault --db data/nayvadius.db
python -m nayvadius.cli vault-organization-plan --output /path/to/vault
python -m nayvadius.cli vault-organization-apply --output /path/to/vault
python -m nayvadius.cli vault-organization-apply --output /path/to/vault --apply
```

Merge plans separate `AUTO`, `REVIEW`, and `SKIP` candidates. Vault organization plans separately identify deterministic `AUTO` relocations, conflicts requiring `REVIEW`, and safe `SKIP` cases. Only explicit `--apply` changes files. Only `AUTO` candidates
can be applied, and only when `--apply` is explicitly provided. Changed notes are
backed up under `.nayvadius-backup/` with a hash and operation manifest; original
vault files are never permanently discarded. The maintenance command writes
`nayvadius_maintenance_report.json` and compares entity files, links, provenance,
aliases, and relation endpoints with the SQLite database.


## DB ↔ Vault reconciliation

The deterministic reconciliation planner cross-checks Obsidian vault changes against Nayvadius document identity using the vault SHA-256 and `documents.content_hash`. Exact content-preserving moves become `AUTO` only when exactly one DB document matches; ambiguous, unmatched, added, deleted, and modified notes remain `REVIEW` with DB provenance details attached.

```bash
python -m nayvadius.cli db-reconcile-plan --output /path/to/vault --db data/nayvadius.db
```

On first run, this creates `vault_snapshot.json` as a baseline. Subsequent runs compare the live vault against that snapshot and write `db_reconciliation_plan.json`. The command is analysis-only: it never mutates the vault or database. The snapshot is updated only after the reconciliation plan is produced.

## Live Obsidian bridge

The live bridge connects to the user's running Obsidian instance through the Local REST API
on the same macOS runner. It mirrors Markdown into an isolated temporary workspace, runs
the existing deterministic audit/normalization/entity-merge engine, then writes only the
resulting changes back through the REST API. Each overwrite/delete is backed up in the
vault under `.nayvadius-backup/live-rest/<timestamp>/`, and a remote note is never
overwritten
if its content changed after the mirror was taken.

The scheduled/manual workflow is:
`.github/workflows/obsidian-live-sync.yml`

It uses the Local REST API key from
`.obsidian/plugins/obsidian-local-rest-api/data.json` on the Mac runner when
`OBSIDIAN_API_KEY` is not explicitly supplied. The default live vault is
`/Users/w/Desktop/Invest/Invest Insight` and the default HTTPS endpoint is
`https://127.0.0.1:27124`.

The bridge intentionally excludes hidden paths (including `.obsidian/`) and non-Markdown
attachments from the reconciliation mirror, so plugin configuration and binary assets are
not rewritten by Nayvadius.
