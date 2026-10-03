import argparse

def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=["status", "process"])
    args = parser.parse_args()
    if args.command == "status":
        print("Nayvadius V0: ready")
    else:
        print("Nayvadius V0: processing pipeline not connected yet")

if __name__ == "__main__":
    main()
