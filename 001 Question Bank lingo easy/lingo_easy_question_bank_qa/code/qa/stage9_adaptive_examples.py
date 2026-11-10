"""Stage 9: build example adaptive profiles from SYNTHETIC learners (simulated responses; no real learner data exists)."""
import json
import math
import random
import tempfile
from pathlib import Path

from adaptive.attempts import build_attempt_records, load_sidecars
from adaptive.profile import build_profile
from assembler.assemble import assemble
from .common import *  # noqa: F401,F403
from .minischema import validate

LEARNERS = [
    {"learner_id": "synthetic-strong-b2", "theta": 6.0, "attempts": [("placement", None), ("assessment", "B2")], "answer_rate": 1.0},
    {"learner_id": "synthetic-weak-a2", "theta": 3.0, "attempts": [("placement", None)], "answer_rate": 1.0},
    {"learner_id": "synthetic-skipper", "theta": 5.0, "attempts": [("placement", None)], "answer_rate": 0.06},
]


def simulate(stored, theta, answer_rate, rng):
    ans = {}
    for qid, k in stored["key"].items():
        if rng.random() > answer_rate:
            continue
        p_known = 1 / (1 + math.exp(-(theta - k["band"]) / 0.9))
        p = 1 / 3 + (2 / 3) * p_known
        if rng.random() < p:
            ans[qid] = k["answer"]
        else:
            ans[qid] = rng.choice([c for c in "ABC" if c != k["answer"]])
    return ans


def run():
    meta, diag = load_sidecars()
    sch_a = json.loads((OUT / "schemas" / "learner_attempt_schema.json").read_text(encoding="utf-8"))
    sch_p = json.loads((OUT / "schemas" / "adaptive_profile_schema.json").read_text(encoding="utf-8"))
    out = OUT / "docs" / "examples"
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for i, L in enumerate(LEARNERS):
        rng = random.Random(1000 + i)
        attempts = {}
        for j, (mode, lv) in enumerate(L["attempts"]):
            d = BANK if mode == "placement" else BANK / "assessment" / lv
            _, st = assemble(d, seed=500 + 10 * i + j, level=lv)
            answers = simulate(st, L["theta"], L["answer_rate"], rng)
            aid = f"{L['learner_id']}-a{j + 1}"
            attempts[aid] = build_attempt_records(st, answers, meta, diag, L["learner_id"], aid, "2026-01-01T00:00:00+00:00")
        prof = build_profile(L["learner_id"], attempts, now="2026-01-01T00:00:00+00:00")
        prof["synthetic"] = True
        prof["synthetic_note"] = f"Simulated learner (theta={L['theta']} on the 1-9 band scale, answer_rate={L['answer_rate']}). Not real data."
        errs = validate(prof, sch_p) + [e for recs in attempts.values() for r in recs for e in validate(r, sch_a)]
        write_json(out / f"profile_{L['learner_id']}.json", prof)
        write_json(out / f"attempts_{L['learner_id']}_sample.json", [r for recs in attempts.values() for r in recs][:12])
        summary.append({"learner": L["learner_id"], "status": prof["status"], "cefr": prof["cefr_estimate"]["level"], "schema_errors": len(errs),
                        "weaknesses": [s for s, v in prof["subskills"].items() if v["status"] == "weakness"], "patterns": len(prof["error_patterns"])})
    print(summary)
    return summary


if __name__ == "__main__":
    run()
