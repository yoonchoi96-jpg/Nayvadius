import argparse
from .engine import Engine
from .db import status

def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process"])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()

    if args.command == "status":
        print(status())
    else:
        print(Engine(args.output).run(args.input))

if __name__ == "__main__":
    main()
