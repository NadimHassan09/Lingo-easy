"""Apply distractor patches (qa/patches/*.json) to the question bank with a full audit trail.

Rules enforced: the correct option text and its letter are never changed; UUIDs/ids are untouched; new option texts must be
distinct within the item; every change is logged with original and revised content in audit/question_change_log.jsonl.
Usage: python -m qa.apply_patches [--dry-run]
"""
import argparse
import datetime
import glob
import json
import subprocess
import sys

from .common import *  # noqa: F401,F403

TOOL = "claude-sonnet-5-5 (LLM-assisted rewrite; not independently human-reviewed)"


def run(dry=False):
    entries = {e["part"]["id"]: e for e in load_parts()}
    log, touched = [], set()
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    problems = []
    applied_file = ROOT / "qa" / "patches" / "applied.json"
    applied = json.loads(applied_file.read_text(encoding="utf-8")) if applied_file.exists() else []
    new_applied = []
    for pf in sorted(glob.glob(str(ROOT / "qa" / "patches" / "patch_*.json"))):
        patch_name = Path(pf).stem
        if patch_name in applied:
            continue
        new_applied.append(patch_name)
        for p in json.loads(Path(pf).read_text(encoding="utf-8")):
            qid = p["id"]
            pid = qid.rsplit("-Q", 1)[0]
            e = entries.get(pid)
            if not e:
                problems.append((qid, "part not found"))
                continue
            part = e["part"]
            it = next((i for _, i in items_of(part) if i["id"] == qid), None)
            if it is None:
                problems.append((qid, "item not found"))
                continue
            before = json.loads(json.dumps(it))
            texts = {o["id"]: o["text"] for o in it["options"]}
            bad = [k for k in p["set"] if k == it["answer"] or k not in texts]
            if bad:
                problems.append((qid, f"patch touches key or unknown option {bad}"))
                continue
            new = dict(texts)
            new.update(p["set"])
            if len({norm(v) for v in new.values()}) != len(new):
                problems.append((qid, "duplicate option text after patch"))
                continue
            for o in it["options"]:
                o["text"] = new[o["id"]]
            changed = [k for k in p["set"] if texts[k] != p["set"][k]]
            if not changed:
                continue
            touched.add(pid)
            log.append({
                "question_id": qid, "uuid": it["uuid"], "part_id": pid, "source_file": e["rel"], "patch_file": patch_name,
                "fields_modified": [f"options[{k}].text" for k in changed],
                "original": {"options": before["options"], "answer": before["answer"], "level": before["level"], "skill_tag": before["skill_tag"]},
                "revised": {"options": it["options"], "answer": it["answer"], "level": it["level"], "skill_tag": it["skill_tag"]},
                "answer_changed": False, "level_changed": False, "tags_changed": False,
                "reason": p["reason"], "evidence": (before.get("evidence") or {}),
                "review_confidence": p.get("confidence", "medium"), "human_review_still_required": True,
                "review_timestamp": ts, "tool": TOOL,
            })
    if problems:
        for q, m in problems:
            print("PROBLEM", q, m)
    print(f"{len(log)} item changes in {len(touched)} parts; problems={len(problems)}")
    if dry:
        return log, problems
    for pid in touched:
        e = entries[pid]
        e["path"].write_text(json.dumps(e["part"], ensure_ascii=False, indent=2), encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_part.py"), str(e["path"]), "--stamp"], capture_output=True, check=True)
    applied_file.write_text(json.dumps(applied + new_applied, indent=1), encoding="utf-8")
    AUDIT.mkdir(parents=True, exist_ok=True)
    with open(AUDIT / "question_change_log.jsonl", "a", encoding="utf-8") as f:
        for r in log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    full = [json.loads(l) for l in open(AUDIT / "question_change_log.jsonl", encoding="utf-8")]
    write_csv(AUDIT / "question_change_summary.csv", [{
        "question_id": r["question_id"], "uuid": r["uuid"], "part_id": r["part_id"], "source_file": r["source_file"], "patch_file": r["patch_file"],
        "fields_modified": ";".join(r["fields_modified"]), "answer_changed": r["answer_changed"], "reason": r["reason"],
        "review_confidence": r["review_confidence"], "human_review_still_required": r["human_review_still_required"], "review_timestamp": r["review_timestamp"]}
        for r in full])
    return log, problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
