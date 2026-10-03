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
