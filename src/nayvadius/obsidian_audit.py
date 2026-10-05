import json
import re
from pathlib import Path

from .processor import ENTITY_TYPES

WIKI_RE = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]+)?\]\]")


def _iter_markdown(root):
    return sorted(Path(root).rglob("*.md")) if Path(root).exists() else []


def audit_vault(root):
    root = Path(root)
    errors, warnings = [], []
    if not root.exists():
        return {"status":"FAIL","root":str(root),"files":0,"entity_notes":0,"errors":[f"vault root does not exist: {root}"],"warnings":[]}
    files = _iter_markdown(root)
    entity_root = root / "entities"
    entity_names = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        if rel.startswith("entities/"):
            parts = Path(rel).parts
            if len(parts) >= 2 and not path.name.startswith("_"):
                domain = parts[1] if len(parts) > 1 else ""
                if domain not in ENTITY_TYPES:
                    errors.append(f"legacy/unknown entity domain: {rel}")
                else:
                    entity_names.setdefault(path.stem, []).append(domain)
    for name, domains in sorted(entity_names.items()):
        unique = sorted(set(domains))
        if len(unique) > 1:
            warnings.append({"kind":"duplicate_entity_stem","name":name,"domains":unique})
    targets = {p.stem for p in files}
    for path in files:
        text = path.read_text(encoding="utf-8")
        for target in WIKI_RE.findall(text):
            target = target.strip()
            if target and not target.startswith("http") and target not in targets:
                warnings.append({"kind":"unresolved_wikilink","file":str(path.relative_to(root)),"target":target})
    return {"status":"FAIL" if errors else "PASS","root":str(root),"files":len(files),"entity_notes":sum(len(v) for v in entity_names.values()),"errors":errors,"warnings":warnings}


def write_audit_report(report, path):
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_vault(root, apply=False):
    """Plan/apply safe Obsidian filename/link normalization.

    Only exact, unambiguous wikilinks are rewritten. No entity is deleted or
    merged automatically; ambiguous cases remain warnings for human review.
    """
    root = Path(root)
    report = audit_vault(root)
    changes = []
    for warning in report["warnings"]:
        if warning.get("kind") != "unresolved_wikilink":
            continue
        target = warning["target"]
        candidates = [p for p in _iter_markdown(root) if p.stem.casefold() == target.casefold()]
        if len(candidates) != 1:
            continue
        path = root / warning["file"]
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(r"\\[\\[" + re.escape(target) + r"\\]\\]", re.IGNORECASE)
        new_text, count = pattern.subn("[[" + candidates[0].stem + "]]", text)
        if count and new_text != text:
            changes.append({"file": warning["file"], "target": target, "replacement": candidates[0].stem, "count": count})
            if apply:
                path.write_text(new_text, encoding="utf-8")
    return {"applied": apply, "changes": changes, "audit_before": report}
