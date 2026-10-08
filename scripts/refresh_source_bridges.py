#!/usr/bin/env python3
"""Refresh cross-plugin provenance bridges after source ingestion.

This step is deliberately deterministic: it never performs semantic matching.
A bridge is created only when the same canonical (name, entity_type) already
has provenance from at least two distinct source adapters.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nayvadius.db import connect
from nayvadius.source_bridges import derive_source_bridge_links


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/nayvadius.db")
    parser.add_argument("--output", default="output/source_bridge_report.json")
    args = parser.parse_args()

    db = connect(args.db)
    try:
        count = derive_source_bridge_links(db)
        db.commit()
    finally:
        db.close()

    result = {
        "status": "OK",
        "db": str(Path(args.db)),
        "source_bridge_links": count,
        "rule": "shared_canonical_entity",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
