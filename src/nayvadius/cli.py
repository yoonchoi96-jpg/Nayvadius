import argparse
from .engine import run

def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process"])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.command == "status":
        print("Nayvadius V3: ready")
    else:
        print(f"processed={run(args.input, args.output)}")

if __name__ == "__main__":
    main()

# V5 CLI compatibility
