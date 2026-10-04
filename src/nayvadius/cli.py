import argparse
from .engine import Engine
from .db import status, failed_document_ids
from .adapters import load_abraham_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process", "retry-failed"])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--output", default="output")
    parser.add_argument("--source", choices=["jsonl", "abraham"], default="abraham")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()

    if args.command == "status":
        print(status())
        return

    engine = Engine(args.output)
    if args.source == "abraham":
        records = load_abraham_jsonl(args.input)
        if args.command == "retry-failed":
            failed = set(failed_document_ids(args.max_attempts))
            records = [r for r in records if r.document.id in failed]
            print(engine.run_processed(records))
        else:
            print(engine.run_processed(records, offset=args.offset, limit=args.limit))
    else:
        print(engine.run(args.input, offset=args.offset, limit=args.limit))


if __name__ == "__main__":
    main()
