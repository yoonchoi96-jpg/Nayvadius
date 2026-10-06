import argparse
import json
from pathlib import Path
from .engine import Engine
from .db import status, failed_document_ids, merge_entity
from .qa import audit_database, write_report
from .adapters import load_abraham_jsonl, load_abel, load_jacques_json
from .obsidian_audit import (
    audit_vault, audit_vault_database, maintenance_report, normalize_vault, snapshot_vault,
    build_entity_merge_plan, write_audit_report, write_merge_plan,
    write_maintenance_report, apply_entity_merge_plan,
)
from .reconciliation import (\n    build_live_db_reconciliation_plan, write_db_reconciliation_plan, write_vault_snapshot,\n)\nfrom .vault_organization import (
    build_vault_organization_plan, write_vault_organization_plan,
    apply_vault_organization_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="nayvadius")
    parser.add_argument("command", choices=[
        "status", "process", "retry-failed", "qa", "obsidian-audit",
        "obsidian-normalize", "entity-merge-plan", "entity-merge-apply",
        "vault-organization-plan", "vault-organization-apply", "db-reconcile-plan", "maintenance",
    ])
    parser.add_argument("--input", default="data/input.jsonl")
    parser.add_argument("--db", default="data/nayvadius.db")
    parser.add_argument("--output", default="output")
    parser.add_argument("--source", choices=["jsonl", "abraham", "abel", "jacques"], default="abraham")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--max-attempts", type=int, default=5)\n    parser.add_argument("--snapshot", default="")
    args = parser.parse_args()

    if args.command == "db-reconcile-plan":
        snapshot_path = Path(args.snapshot or (str(args.output).rstrip("/") + "/vault_snapshot.json"))
        plan_path = Path(str(args.output).rstrip("/") + "/db_reconciliation_plan.json")
        if not snapshot_path.exists():
            current = snapshot_vault(args.output)
            write_vault_snapshot(current, snapshot_path)
            print(json.dumps({
                "status": "BASELINE_CREATED",
                "snapshot": str(snapshot_path),
                "message": "No previous snapshot existed; baseline created. Re-run to reconcile changes.",
            }, ensure_ascii=False, indent=2))
            return
        with snapshot_path.open(encoding="utf-8") as fh:
            previous = json.load(fh)
        current, plan = build_live_db_reconciliation_plan(previous, args.output, args.db)
        write_db_reconciliation_plan(plan, plan_path)
        write_vault_snapshot(current, snapshot_path)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if plan["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "vault-organization-apply":
        plan_path = str(args.output).rstrip("/") + "/vault_organization_plan.json"
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        result = apply_vault_organization_plan(args.output, plan, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "vault-organization-plan":
        plan = build_vault_organization_plan(args.output)
        path = str(args.output).rstrip("/") + "/vault_organization_plan.json"
        write_vault_organization_plan(plan, path)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if plan["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "entity-merge-apply":
        plan_path = str(args.output).rstrip("/") + "/entity_merge_plan.json"
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        result = apply_entity_merge_plan(args.output, plan, apply=args.apply)
        db_merges = []
        if args.apply:
            for item in result.get("applied", []):
                canonical = Path(item["canonical"]).stem
                duplicate = Path(item["merged"]).stem
                entity_type = Path(item["canonical"]).parts[1] if len(Path(item["canonical"]).parts) > 1 else ""
                if entity_type:
                    merged = merge_entity(
                        canonical, duplicate, entity_type,
                        reason="exact_name", db_path=args.db,
                    )
                    db_merges.append({
                        "canonical": canonical, "duplicate": duplicate,
                        "entity_type": entity_type, "merged": merged,
                    })
        result["db_merges"] = db_merges
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "entity-merge-plan":
        plan = build_entity_merge_plan(args.output)
        path = str(args.output).rstrip("/") + "/entity_merge_plan.json"
        write_merge_plan(plan, path)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    if args.command == "obsidian-normalize":
        result = normalize_vault(args.output, apply=getattr(args, "apply", False))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "obsidian-audit":
        report = audit_vault(args.output)
        consistency = audit_vault_database(args.output, args.db)
        report["db_consistency"] = consistency
        if consistency["errors"]:
            report["status"] = "FAIL"
            report["summary"]["error"] += consistency["summary"]["error"]
        report_path = str(args.output).rstrip("/") + "/obsidian_audit_report.json"
        write_audit_report(report, report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "maintenance":
        report = maintenance_report(args.output, args.db)
        report_path = str(args.output).rstrip("/") + "/nayvadius_maintenance_report.json"
        write_maintenance_report(report, report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "qa":
        report = audit_database(args.db)
        report_path = str(args.output).rstrip("/") + "/qa_report.json"
        write_report(report, report_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "status":
        print(status())
        return

    engine = Engine(args.output)
    if args.source == "jacques":
        if args.command == "retry-failed":
            raise SystemExit("retry-failed is only supported for document sources")
        records = load_jacques_json(args.input)
        print(engine.run_processed(records, offset=args.offset, limit=args.limit))
    elif args.source == "abel":
        if args.command == "retry-failed":
            raise SystemExit("retry-failed is only supported for document sources")
        records = load_abel(args.input)
        print(engine.run_vocabulary(records, offset=args.offset, limit=args.limit))
    elif args.source == "abraham":
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
