import argparse
from .engine import Engine
from .db import status
from .adapters import load_abraham_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process"])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--output", default="output")
    parser.add_argument("--source", choices=["jsonl", "abraham"], default="abraham")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if args.command == "status":
        print(status())
        return

    engine = Engine(args.output)
    if args.source == "abraham":
        records = load_abraham_jsonl(args.input)
        print(engine.run_processed(records, offset=args.offset, limit=args.limit))
    else:
        print(engine.run(args.input, offset=args.offset, limit=args.limit))


if __name__ == "__main__":
    main()
