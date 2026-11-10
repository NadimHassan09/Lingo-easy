"""Stage 8: multi-seed distribution audit of the REAL assembler (assembler/assemble.py), with and without blueprint enforcement.

Usage: python -m qa.stage8_simulation [N_SEEDS]   (default 1000 per exam type)
The only thing replaced is bank loading (memoised in-process for speed); selection, shuffling and blueprint logic are the real code.
"""
import hashlib
import json
import statistics
import sys
import time
from collections import Counter, defaultdict

import assembler.assemble as A
from assembler.blueprint import CEFR, BlueprintError, exam_metrics, exam_type_for, load_blueprint, load_meta, validate_exam
from .common import *  # noqa: F401,F403

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
_orig = A.load_bank
_cache = {}


def cached_load_bank(d, statuses):
    k = (str(d), tuple(statuses))
    if k not in _cache:
        _cache[k] = _orig(d, statuses)
    return _cache[k]


A.load_bank = cached_load_bank


def sig(public):
    """Deterministic signature of an exam (ignores exam_id/created_at which are random per attempt)."""
    body = json.dumps(public["sections"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def run():
    t0 = time.time()
    bp = load_blueprint()
    meta = load_meta()
    types = [("placement", None, BANK)] + [(f"assessment_{lv}", lv, BANK / "assessment" / lv) for lv in CEFR]
    summary, audit_rows, failures = {}, [], []
    manifests = {}
    for name, lv, d in types:
        spec = bp["exam_types"][name]
        statuses = ["validated", "reviewed", "approved"]
        bank, _ = _orig(d, statuses)
        byid = {p["id"]: p for s in bank.values() for p in s}
        qcount_by_part = {pid: sum(len(g["items"]) for g in p["question_groups"]) for pid, p in byid.items()}
        res = {"enforced": {}, "baseline_no_enforcement": {}}
        for mode, enforce in (("baseline_no_enforcement", False), ("enforced", True)):
            ok, fail, viol_runs = 0, 0, 0
            viol_codes, attempts_hist = Counter(), Counter()
            metr = []
            q_freq, part_freq = Counter(), Counter()
            sets = Counter()
            dup_items = dup_sources = 0
            rows = []
            for seed in range(N):
                try:
                    pub, st = A.assemble(d, seed=seed, level=lv, enforce_blueprint=enforce)
                except (BlueprintError, A.ShortageError) as e:
                    fail += 1
                    failures.append({"exam_type": name, "mode": mode, "seed": seed, "error": getattr(e, "code", type(e).__name__), "message": str(e)[:300],
                                     "violation_counts": json.dumps(getattr(e, "details", {}).get("violation_counts", {}))})
                    rows.append({"seed": seed, "status": "failed"})
                    continue
                parts = [byid[p["part_id"]] for p in st["parts"]]
                m = exam_metrics(parts, meta)
                v = validate_exam(parts, spec, meta, bp.get("forbidden_pairs", []))  # independent re-check of the returned exam
                ok += 1
                if v:
                    viol_runs += 1
                    viol_codes.update(x["code"] for x in v)
                attempts_hist[st["blueprint"]["selection_attempts"]] += 1
                metr.append(m)
                for pid in [p["part_id"] for p in st["parts"]]:
                    part_freq[pid] += 1
                for p in parts:
                    for g in p["question_groups"]:
                        for it in g["items"]:
                            q_freq[it["id"]] += 1
                sets[tuple(sorted(st["parts"][i]["part_id"] for i in range(len(st["parts"]))))] += 1
                dup_items += m["duplicate_item_ids"]
                dup_sources += m["duplicate_sources"]
                rows.append({"seed": seed, "status": "ok", "attempts": st["blueprint"]["selection_attempts"], "parts": ";".join(p["part_id"] for p in st["parts"]),
                             **{f"n_{c}": m["by_level"][c] for c in CEFR}, "violations": ";".join(sorted({x["code"] for x in v}))})
            if mode == "enforced":
                manifests[name] = rows
            n_all_q = [(len(byid), 0)]
            levels = {c: [m["by_level"][c] for m in metr] for c in CEFR}
            subs = defaultdict(lambda: defaultdict(list))
            for m in metr:
                for sk, c in m["by_subskill"].items():
                    for s_, n_ in c.items():
                        subs[sk][s_].append(n_)
            all_q = {it["id"] for p in byid.values() for g in p["question_groups"] for it in g["items"]}
            res[mode] = {
                "seeds_executed": N, "exams_generated": ok, "generation_failures": fail,
                "generation_failure_rate": {"numerator": fail, "denominator": N, "value": round(fail / N, 4)},
                "exams_passing_all_blueprint_constraints": {"numerator": ok - viol_runs, "denominator": N, "value": round((ok - viol_runs) / N, 4),
                                                            "method": "exam returned by assembler re-validated by assembler.blueprint.validate_exam; failures to generate count as not passing"},
                "exams_with_constraint_violation": viol_runs, "violation_codes": dict(viol_codes),
                "duplicate_question_rate": {"numerator": dup_items, "denominator": ok, "value": round(dup_items / max(1, ok), 4)},
                "duplicate_source_rate": {"numerator": dup_sources, "denominator": ok, "value": round(dup_sources / max(1, ok), 4)},
                "selection_attempts_histogram": {str(k): v for k, v in sorted(attempts_hist.items())},
                "level_counts_min_max_mean": {c: [min(v) if v else None, max(v) if v else None, round(statistics.mean(v), 2) if v else None] for c, v in levels.items()},
                "modality_counts": {sk: sorted({m["by_modality"].get(sk, 0) for m in metr}) for sk in ("listening", "reading")},
                "subskill_min_max_mean": {sk: {s_: [min(v), max(v), round(statistics.mean(v), 2)] for s_, v in c.items()} for sk, c in subs.items()},
                "distinct_part_sets": len(sets), "most_common_part_set_share": round(sets.most_common(1)[0][1] / max(1, ok), 4) if sets else None,
                "parts_in_bank": len(byid), "parts_never_selected": sorted(set(byid) - set(part_freq)),
                "part_frequency_min_max": [min(part_freq.values()), max(part_freq.values())] if part_freq else None,
                "questions_in_bank": len(all_q), "questions_never_appearing": len(all_q - set(q_freq)),
                "question_frequency_min_max_mean": [min(q_freq.values()), max(q_freq.values()), round(statistics.mean(q_freq.values()), 1)] if q_freq else None,
            }
            for c in CEFR:
                lo, hi = res[mode]["level_counts_min_max_mean"][c][0], res[mode]["level_counts_min_max_mean"][c][1]
                rng = spec["level_counts"][c]
                audit_rows.append({"exam_type": name, "mode": mode, "metric": f"level_{c}", "min_observed": lo, "max_observed": hi, "mean": res[mode]["level_counts_min_max_mean"][c][2],
                                   "required_min": rng["min"], "required_max": rng["max"], "pass": (lo is not None and lo >= rng["min"] and hi <= rng["max"])})
            for sk in ("listening", "reading"):
                vals = sorted({m["by_modality"].get(sk, 0) for m in metr})
                audit_rows.append({"exam_type": name, "mode": mode, "metric": f"questions_{sk}", "min_observed": vals[0] if vals else None, "max_observed": vals[-1] if vals else None,
                                   "mean": "", "required_min": spec["questions"][sk], "required_max": spec["questions"][sk], "pass": vals == [spec["questions"][sk]]})
            audit_rows.append({"exam_type": name, "mode": mode, "metric": "exams_passing_all_constraints", "min_observed": ok - viol_runs, "max_observed": N, "mean": "",
                               "required_min": N, "required_max": N, "pass": (ok - viol_runs) == N})
        summary[name] = res
        # determinism: same seed twice -> identical selection, shuffles and key
        det = 0
        for seed in range(50):
            p1, s1 = A.assemble(d, seed=seed, level=lv)
            p2, s2 = A.assemble(d, seed=seed, level=lv)
            det += (sig(p1) == sig(p2)) and (s1["key"] == s2["key"])
        summary[name]["determinism_same_seed_identical"] = {"numerator": det, "denominator": 50}
    write_csv(REPORTS / "exam_distribution_audit.csv", audit_rows)
    write_csv(REPORTS / "assembly_failures.csv", failures, ["exam_type", "mode", "seed", "error", "message", "violation_counts"])
    for name, rows in manifests.items():
        fields = ["seed", "status", "attempts", "parts"] + [f"n_{c}" for c in CEFR] + ["violations"]
        write_csv(OUT / "exam_manifests" / f"manifest_{name}.csv", rows, fields)
    write_json(REPORTS / "assembly_simulation_summary.json", {
        "assembler": "assembler/assemble.py (real code; bank loading memoised in-process)", "blueprint": "config/exam_blueprint_v1.json v1.0",
        "seeds_per_exam_type_and_mode": N, "exam_types": list(summary), "elapsed_seconds": round(time.time() - t0, 1),
        "note": "baseline_no_enforcement = legacy assembly (enforce_blueprint=False) evaluated against the blueprint; enforced = current assembler",
        "results": summary})
    for name, res in summary.items():
        e, b = res["enforced"], res["baseline_no_enforcement"]
        print(f"{name:16s} enforced pass {e['exams_passing_all_blueprint_constraints']['numerator']}/{N} fail {e['generation_failures']} attempts {e['selection_attempts_histogram']}"
              f" | baseline pass {b['exams_passing_all_blueprint_constraints']['numerator']}/{N} {b['violation_codes']}")


if __name__ == "__main__":
    run()
