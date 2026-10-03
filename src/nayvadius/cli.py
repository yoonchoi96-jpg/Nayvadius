import argparse
from .engine import Engine
from .db import status


def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process"])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--output", default="output")
    parser.add_argument("--source", choices=["jsonl", "readwise"], default="jsonl")
    parser.add_argument("--location", default="archive")
    parser.add_argument("--source-limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.command == "status":
        print(status())
        return

    engine = Engine(args.output)
    if args.source == "readwise":
        from .adapters import ReadwiseReaderAdapter
        docs = ReadwiseReaderAdapter(location=args.location, limit=args.source_limit).load()
        print(engine.run_documents(docs, offset=args.offset, limit=args.limit))
    else:
        print(engine.run(args.input, offset=args.offset, limit=args.limit))


if __name__ == "__main__":
    main()
