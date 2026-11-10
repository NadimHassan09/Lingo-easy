"""Audit trail for the Writing/Speaking content: compare the parts produced by the previous implementation (a snapshot directory laid out as
<skill>/placement|assessment/<LEVEL>/<ID>/part.json) with the parts now in question_bank/, and classify every change.

Usage: python -m productive.audit [--before backups/productive_bank_pre_audit] [--bank question_bank] [--out lingo_easy_writing_speaking/reports]
Outputs: audit_log.jsonl (one line per part with changed field groups and before/after for learner-facing text), audit_summary.json, audit_parts.csv

Classification of a part:
  unchanged_content     learner-facing task, rubric criteria, classification and difficulty identical (only additive metadata / version / provenance differ)
  metadata_aligned      additive Lingo Easy metadata added (part_type, level, ielts_reference, skill_tag), nothing else changed
  content_modified      learner-facing task text/category changed (a real audit fix), listed per field
  rubric_modified       evaluation blueprint changed (weights/criteria)
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from .common import BANK, LEVELS, ROOT, load_json, write_csv, write_json

OUT = ROOT / "lingo_easy_writing_speaking" / "reports"
ADDITIVE = {"part_type", "level", "ielts_reference", "skill_tag"}
VOLATILE = {"provenance", "qa", "meta", "derived", "version"}


def old_parts(root):
    out = {}
    for p in sorted(Path(root).glob("**/part.json")):
        d = load_json(p)
        out[d["id"]] = d
    return out


def new_parts(bank):
    out = {}
    for p in sorted(Path(bank).glob("**/part.json")):
        d = load_json(p)
        if d.get("skill") in ("writing", "speaking"):
            out[d["id"]] = (d, p)
    return out


def flat_diff(a, b, path=""):
    """Paths that differ between two JSON values (lists compared as a whole)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}" if path else k)
            elif k not in b:
                out.append(f"{path}.{k}" if path else k)
            else:
                out += flat_diff(a[k], b[k], f"{path}.{k}" if path else k)
        return out
    return [] if a == b else [path]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=str(ROOT / "backups" / "productive_bank_pre_audit"))
    ap.add_argument("--bank", default=str(BANK))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    old, new = old_parts(a.before), new_parts(a.bank)
    log, rows, counts = [], [], {"unchanged_content": 0, "metadata_aligned": 0, "content_modified": 0, "rubric_modified": 0, "newly_generated": 0, "missing_in_new": 0}
    for pid in sorted(set(old) | set(new)):
        if pid not in new:
            counts["missing_in_new"] += 1
            rows.append({"part_id": pid, "classification": "missing_in_new", "changed_fields": ""})
            continue
        n, path = new[pid]
        if pid not in old:
            counts["newly_generated"] += 1
            rows.append({"part_id": pid, "skill": n["skill"], "classification": "newly_generated", "changed_fields": ""})
            log.append({"part_id": pid, "classification": "newly_generated", "path": path.relative_to(ROOT).as_posix()})
            continue
        o = old[pid]
        diff = [d for d in flat_diff(o, n) if d.split(".")[0] not in VOLATILE]
        top = {d.split(".")[0] for d in diff}
        task_changes = [d for d in diff if d.startswith(("task", "task_category", "task_format", "expected_response", "topic", "title", "context"))]
        rubric = [d for d in diff if d.startswith("evaluation_blueprint")]
        substantive = [d for d in diff if d.split(".")[0] not in ADDITIVE and d.split(".")[0] not in ("difficulty", "diagnostics", "modality")]
        diff_other = [d for d in diff if d not in task_changes and d not in rubric]
        if task_changes:
            cls = "content_modified"
        elif rubric:
            cls = "rubric_modified"
        elif diff and all(d.split(".")[0] in ADDITIVE or d.startswith("difficulty") for d in diff):
            cls = "metadata_aligned"
        elif not diff:
            cls = "unchanged_content"
        else:
            cls = "metadata_aligned"
        counts[cls] += 1
        entry = {"part_id": pid, "skill": n["skill"], "id_preserved": o["id"] == n["id"], "uuid_preserved": o["uuid"] == n["uuid"], "classification": cls,
                 "changed_fields": diff, "version_before": o.get("version"), "version_after": n.get("version"), "path": path.relative_to(ROOT).as_posix()}
        if task_changes:
            entry["before"] = {k: o.get(k) if k in o else None for k in ("task_category", "task_format") if k in o}
            entry["before"]["task"] = o["task"]
            entry["after"] = {k: n.get(k) for k in ("task_category", "task_format") if k in n}
            entry["after"]["task"] = n["task"]
        if rubric:
            entry["rubric_before_weights"] = {c["id"]: c["weight"] for c in o["evaluation_blueprint"]["criteria"]}
            entry["rubric_after_weights"] = {c["id"]: c["weight"] for c in n["evaluation_blueprint"]["criteria"]}
        log.append(entry)
        rows.append({"part_id": pid, "skill": n["skill"], "bank": n["assessment"]["level"] or "placement", "classification": cls, "id_preserved": entry["id_preserved"],
                     "uuid_preserved": entry["uuid_preserved"], "changed_fields": ";".join(diff)})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "audit_log.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for e in log:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    write_csv(out / "audit_parts.csv", rows)
    by_path = Counter(".".join(d.split(".")[:2]) for e in log for d in e.get("changed_fields", []) if not isinstance(d, int))
    by_path_noadd = {k: v for k, v in sorted(by_path.items(), key=lambda kv: -kv[1])}
    summary = {"changed_field_counts": by_path_noadd, "parts_found_before": len(old), "parts_found_now": len(new), "parts_reviewed": len(new), "counts": counts,
               "ids_preserved": sum(1 for e in log if e.get("id_preserved")), "uuids_preserved": sum(1 for e in log if e.get("uuid_preserved")),
               "content_modified_parts": [e["part_id"] for e in log if e["classification"] == "content_modified"],
               "rubric_modified_parts": [e["part_id"] for e in log if e["classification"] == "rubric_modified"]}
    write_json(out / "audit_summary.json", summary)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
