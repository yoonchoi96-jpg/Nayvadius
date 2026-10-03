# Nayvadius

Personal knowledge processing system.

## V0 principles

- No self-hosted runner.
- GitHub-hosted Actions only.
- Incremental processing.
- Provider-agnostic AI layer.
- Persistent local/state database.
- Obsidian output first; other destinations are adapters.
- Cloud infrastructure is optional until actual workload requires it.

## Architecture

GitHub -> GitHub Actions -> Nayvadius processor -> state/cache -> output adapters


## V5 pipeline

- **Adapters:** source data is normalized into `Document` objects through a small adapter interface.
- **Incremental state:** SQLite tracks document hashes, extraction results, entities, relations, and LLM cache.
- **AI:** an OpenAI-compatible provider is optional; missing keys or failed extraction fall back to deterministic processing.
- **Obsidian:** documents are emitted as stable-ID Markdown files; entities are grouped by entity type.
- **Graph:** every run emits `output/graph.json` for downstream graph/visualization tooling.
- **Automation:** GitHub Actions can run the pipeline without a self-hosted runner.

The first production source adapter is JSONL. Reader/Readwise/Notion connectors can be added without changing the processing core.
