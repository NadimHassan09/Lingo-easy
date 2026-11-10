"""Stage 10: build the consolidated human review queue (every reason a question still needs a human)."""
import csv
import json
from collections import Counter, defaultdict

from .common import *  # noqa: F401,F403

PRIORITY = {"P1": "must review before release", "P2": "review before release (content was rewritten by an LLM)", "P3": "triage when capacity allows (heuristic signal)"}


def run():
    q = defaultdict(lambda: {"reasons": [], "prio": "P3"})
    base = {}

    def add(qid, uuid, src, prio, reason):
        r = q[qid]
        r["uuid"], r["source_file"] = uuid, src
        r["reasons"].append(reason)
        if prio < r["prio"]:
            r["prio"] = prio
    for line in open(REPORTS / "semantic_review.jsonl", encoding="utf-8"):
        s = json.loads(line)
        base[s["question_id"]] = s
        if s["semantic_status"] == "human_review":
            add(s["question_id"], s["uuid"], s["source_file"], "P1", "automated semantic check found a major issue: " + "; ".join(f["code"] for f in s["findings"] if f["severity"] == "major"))
        if s["semantic_status"] == "fix_applied":
            add(s["question_id"], s["uuid"], s["source_file"], "P2", "distractors rewritten by LLM (" + "; ".join(c["patch"] for c in s["changes_applied"]) + "); no independent human confirmation yet")
        for f in s["findings"]:
            if f["code"] in ("correct_option_lexically_unsupported", "weak_statement_evidence_link", "possible_double_negative", "key_repeats_prompt_words") and s["semantic_status"] != "fix_applied":
                add(s["question_id"], s["uuid"], s["source_file"], "P3", f"{f['code']} (minor): {f['detail'][:80]}")
    for x in csv.DictReader(open(REPORTS / "cefr_reassessment.csv", encoding="utf-8-sig")):
        if x["human_review_required"] == "True":
            add(x["question_id"], x["uuid"], base[x["question_id"]]["source_file"], "P3", f"heuristic CEFR {x['recommended_cefr']} vs recorded {x['original_cefr']} (gap {x['level_gap_steps']}; weak heuristic)")
    for x in csv.DictReader(open(REPORTS / "subskill_validation.csv", encoding="utf-8-sig")):
        if x["result"] == "inconsistent":
            add(x["question_id"], x["uuid"], base[x["question_id"]]["source_file"], "P3", f"skill tag '{x['original_tag']}' fails check {x['check']} (suggested primary: {x['recommended_primary_subskill']})")
    rows = [{"question_id": k, "uuid": v["uuid"], "source_file": v["source_file"], "priority": v["prio"], "n_reasons": len(v["reasons"]), "reasons": " | ".join(dict.fromkeys(v["reasons"])),
             "recommended_action": "independent human review of key, distractors and tags; confirm or revert the patch in audit/question_change_log.jsonl"} for k, v in sorted(q.items(), key=lambda kv: (kv[1]["prio"], kv[0]))]
    write_csv(REPORTS / "human_review_queue.csv", rows)
    c = Counter(r["priority"] for r in rows)
    print(dict(c), len(rows))
    return {"queue_size": len(rows), "by_priority": dict(c), "priority_meaning": PRIORITY}


if __name__ == "__main__":
    run()
