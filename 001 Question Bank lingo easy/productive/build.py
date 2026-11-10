"""Full pipeline: schemas -> generate all 140 parts -> validate -> stamp qa/meta -> write bank -> write reports.

Usage: python -m productive.build [--seed 20261030] [--generated-at ISO] [--out productive_bank] [--reports lingo_easy_writing_speaking/reports]
Exit status 1 when any structural error remains (the bank is still written so the failures can be inspected, with status 'draft').
"""
import argparse
import datetime
import shutil
import sys
from collections import Counter, defaultdict

from . import schemas_build, validate as V
from .common import BANK, LEVELS, LV, ROOT, part_dir, taxonomy, write_csv, write_json
from .generate import generate
from .specs.registry import POOLS

OUT = ROOT / "lingo_easy_writing_speaking"


def bank_of(p):
    return "placement" if p["assessment"]["type"] == "placement" else p["assessment"]["level"]


def stamp(parts, res):
    for p in parts:
        r = res["parts"][p["id"]]
        errs = list(r["schema_errors"]) + [f"{c}: {d}" for s, c, d in r["findings"] if s == "error"]
        warns = [f"{c}: {d}" for s, c, d in r["findings"] if s == "warn"]
        p["qa"]["structural_validation"] = "fail" if errs else "pass"
        p["qa"]["semantic_rule_review"] = "flagged" if warns else "pass"
        p["qa"]["findings"] = [{"severity": "error", "detail": e} for e in errs] + [{"severity": "warn", "detail": w} for w in warns]
        p["meta"]["status"] = "validated" if not errs else "draft"


def reports(parts, res, out):
    tax = taxonomy()
    rep = out
    rep.mkdir(parents=True, exist_ok=True)

    def row(p):
        return {"id": p["id"], "uuid": p["uuid"], "skill": p["skill"], "bank": bank_of(p), "assessment_type": p["assessment"]["type"], "target_cefr": p["target_cefr"],
                "recommended_cefr": p["difficulty"]["recommended_cefr"], "cefr_confidence": p["difficulty"]["cefr_confidence"], "task_type": p.get("task_category") or p.get("task_format"),
                "topic": p["topic"], "title": p["title"], "primary_subskill": p["classification"]["primary_subskill"], "secondary_subskills": p["classification"]["secondary_subskills"],
                "criteria": [c["id"] for c in p["evaluation_blueprint"]["criteria"]], "status": p["meta"]["status"], "structural_validation": p["qa"]["structural_validation"],
                "semantic_rule_review": p["qa"]["semantic_rule_review"], "human_review": p["qa"]["human_review"], "llm_review": p["qa"]["llm_review"], "version": p["version"],
                "content_hash": p["derived"]["content_hash"], "path": (part_dir("question_bank", p["skill"], bank_of(p), p["id"]) / "part.json").as_posix()}

    for sk in ("writing", "speaking"):
        ps = [p for p in parts if p["skill"] == sk]
        write_json(rep / f"{sk}_inventory.json", {
            "skill": sk, "count": len(ps), "by_bank": {b: sum(1 for p in ps if bank_of(p) == b) for b in ["placement"] + LEVELS},
            "evidence_note": "Inventory of GENERATED content. 'validated' = passed structural validation only; no part has been reviewed by an LLM reviewer or by a human.",
            "parts": [row(p) for p in sorted(ps, key=lambda p: p["id"])]})

    def dist(key):
        d = {}
        for sk in ("writing", "speaking"):
            for b in ["placement"] + LEVELS:
                d.setdefault(sk, {})[b] = dict(Counter(key(p) for p in parts if p["skill"] == sk and bank_of(p) == b))
        return d

    cefr = {"note": "target_cefr is the author's intended level; recommended_cefr is the independent heuristic (uncalibrated).", "target_by_bank": dist(lambda p: p["target_cefr"]),
            "recommended_by_bank": dist(lambda p: p["difficulty"]["recommended_cefr"]),
            "agreement": {sk: {"exact": sum(1 for p in parts if p["skill"] == sk and p["difficulty"]["level_gap_steps"] == 0), "total": sum(1 for p in parts if p["skill"] == sk),
                               "within_one": sum(1 for p in parts if p["skill"] == sk and p["difficulty"]["level_gap_steps"] <= 1)} for sk in ("writing", "speaking")},
            "heuristic_confidence": {sk: dict(Counter(p["difficulty"]["cefr_confidence"] for p in parts if p["skill"] == sk)) for sk in ("writing", "speaking")}}
    write_json(rep / "cefr_distribution.json", cefr)
    write_json(rep / "task_type_distribution.json", {"by_bank": dist(lambda p: p.get("task_category") or p.get("task_format")),
                                                      "overall": {sk: dict(Counter(p.get("task_category") or p.get("task_format") for p in parts if p["skill"] == sk)) for sk in ("writing", "speaking")}})
    write_json(rep / "topic_distribution.json", {"by_bank": dist(lambda p: p["topic"]), "overall": {sk: dict(Counter(p["topic"] for p in parts if p["skill"] == sk)) for sk in ("writing", "speaking")}})
    write_json(rep / "subskill_distribution.json", {"primary": {sk: dict(Counter(p["classification"]["primary_subskill"] for p in parts if p["skill"] == sk)) for sk in ("writing", "speaking")},
                                                    "secondary": {sk: dict(Counter(s for p in parts if p["skill"] == sk for s in p["classification"]["secondary_subskills"])) for sk in ("writing", "speaking")},
                                                    "criteria_usage": {sk: dict(Counter(c["id"] for p in parts if p["skill"] == sk for c in p["evaluation_blueprint"]["criteria"])) for sk in ("writing", "speaking")}})
    # semantic review (rule-based) and human review queue
    sem, queue = [], []
    for p in sorted(parts, key=lambda p: p["id"]):
        r = res["parts"][p["id"]]
        errs = [f"{c}: {d}" for s, c, d in r["findings"] if s == "error"] + r["schema_errors"]
        warns = [f"{c}: {d}" for s, c, d in r["findings"] if s == "warn"]
        sem.append({"part_id": p["id"], "skill": p["skill"], "bank": bank_of(p), "target_cefr": p["target_cefr"], "structural_validation": p["qa"]["structural_validation"],
                    "semantic_rule_review": p["qa"]["semantic_rule_review"], "errors": len(errs), "warnings": len(warns), "findings": " | ".join(errs + warns),
                    "heuristic_cefr": p["difficulty"]["recommended_cefr"], "cefr_gap": p["difficulty"]["level_gap_steps"], "evidence_class": "automated_rules_only",
                    "llm_review": "not_performed", "human_review": "not_reviewed"})
        gap, conf = p["difficulty"]["level_gap_steps"], p["difficulty"]["cefr_confidence"]
        reasons = ["no human review has taken place"]
        if errs:
            prio = "P1"
            reasons += errs
        else:
            prio = "P1" if gap >= 2 else ("P2" if gap == 1 or any(not w.startswith("cefr_confidence_low") for w in warns) else "P3")
            reasons += warns
        if p["skill"] == "speaking":
            reasons.append("typed-text MVP: pronunciation/fluency not assessable; confirm prompts work as written tasks")
        queue.append({"part_id": p["id"], "skill": p["skill"], "bank": bank_of(p), "target_cefr": p["target_cefr"], "priority": prio, "n_reasons": len(reasons), "reasons": " | ".join(reasons),
                      "recommended_action": "independent educator review of prompt clarity, level, rubric and cultural suitability; mark reviewed/approved in meta.status only after sign-off"})
    write_csv(rep / "semantic_review.csv", sem)
    write_csv(rep / "human_review_queue.csv", sorted(queue, key=lambda r: (r["priority"], r["part_id"])))
    dup_fields = ["skill", "part_a", "part_b", "level_a", "level_b", "prompt_jaccard", "task_content_jaccard", "objective_jaccard", "outline_jaccard", "reasons", "severity"]
    write_csv(rep / "duplicate_candidates.csv", res["duplicates"], dup_fields)
    write_json(rep / "structural_validation.json", {"parts_checked": len(parts), "bank_errors": res["bank_errors"], "bank_warnings": res["bank_warnings"],
                                                    "parts_with_schema_errors": [k for k, v in res["parts"].items() if v["schema_errors"]],
                                                    "parts_with_rule_errors": [k for k, v in res["parts"].items() if any(f[0] == "error" for f in v["findings"])],
                                                    "counts": {sk: {b: sum(1 for p in parts if p["skill"] == sk and bank_of(p) == b) for b in ["placement"] + LEVELS} for sk in ("writing", "speaking")}})
    # placement design
    place = {}
    for sk in ("writing", "speaking"):
        ps = sorted([p for p in parts if p["skill"] == sk and bank_of(p) == "placement"], key=lambda p: (LV[p["target_cefr"]], p["id"]))
        place[sk] = {"level_counts": dict(Counter(p["target_cefr"] for p in ps)),
                     "difficulty_progression": [{"id": p["id"], "target": p["target_cefr"], "heuristic": p["difficulty"]["recommended_cefr"], "difficulty_index": p["difficulty"]["difficulty_index"],
                                                  "task_type": p.get("task_category") or p.get("task_format"), "topic": p["topic"], "primary_subskill": p["classification"]["primary_subskill"],
                                                  "evidence_provided": p["difficulty"]["cognitive_demand"]} for p in ps],
                     "limitations": ["One task at A1 and one at C2 gives presence of evidence only, not a reliable estimate at the extremes.",
                                     "Two tasks at each middle level are insufficient to separate adjacent levels with confidence.",
                                     "Ten tasks per skill is a product constraint, not psychometric reliability. Placement estimates need empirical calibration with learner data.",
                                     "The task order a learner sees (adaptive or fixed) is a product decision not made here."]}
    banks_summary = {sk: {b: [{"id": p["id"], "title": p["title"], "type": p.get("task_category") or p.get("task_format"), "topic": p["topic"]}
                              for p in sorted(parts, key=lambda p: p["id"]) if p["skill"] == sk and bank_of(p) == b] for b in ["placement"] + LEVELS} for sk in ("writing", "speaking")}
    summary = {"generated_at": parts[0]["provenance"]["generated_at"], "generator": parts[0]["provenance"]["generator"] + "@" + parts[0]["provenance"]["generator_version"], "seed": parts[0]["provenance"]["seed"],
               "totals": {"writing": sum(1 for p in parts if p["skill"] == "writing"), "speaking": sum(1 for p in parts if p["skill"] == "speaking"), "required": {"writing": 70, "speaking": 70}},
               "per_bank": {sk: {b: sum(1 for p in parts if p["skill"] == sk and bank_of(p) == b) for b in ["placement"] + LEVELS} for sk in ("writing", "speaking")},
               "status_counts": dict(Counter(p["meta"]["status"] for p in parts)),
               "structural_validation": dict(Counter(p["qa"]["structural_validation"] for p in parts)),
               "semantic_rule_review": dict(Counter(p["qa"]["semantic_rule_review"] for p in parts)),
               "llm_review": "not performed (the authoring model's own output was not independently reviewed by a second system)",
               "human_review": "none: no part is reviewed or approved",
               "runtime_llm_calls": 0, "authoring_model": parts[0]["provenance"]["authoring"]["model"],
               "duplicates": {"candidates": len(res["duplicates"]), "confirmed_duplicates": sum(1 for d in res["duplicates"] if d["severity"] == "duplicate")},
               "placement_design": place, "bank_contents": banks_summary,
               "evidence_classes": {"A_automated_structural": "executed by productive.validate", "B_automated_semantic_rules": "executed by productive.validate (rules, not understanding)",
                                    "C_llm_review": "none", "D_human_review": "none", "E_learner_data": "none"}}
    write_json(rep / "generation_summary.json", summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--generated-at", default=None)
    ap.add_argument("--out", default=str(BANK))
    ap.add_argument("--reports", default=str(OUT / "reports"))
    ap.add_argument("--keep-existing", action="store_true", help="do not clear the output bank first")
    a = ap.parse_args(argv)
    schemas_build.main()
    ts = a.generated_at or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    parts = []
    for sk in ("writing", "speaking"):
        for b in POOLS[sk]:
            parts += generate(sk, b, None, a.seed, ts)
    # reload the schema cache in case schemas were just rebuilt
    V.SCHEMAS.update({s: V.load_json(ROOT / "schemas" / f"{s}_part.schema.json") for s in ("writing", "speaking")})
    res = V.validate_all(parts)
    stamp(parts, res)
    out = a.out
    if not a.keep_existing:  # remove only previously generated Writing/Speaking folders; Reading/Listening content is never touched
        root = __import__("pathlib").Path(out)
        for sk in ("writing", "speaking"):
            for d in [root / "placement_test" / sk] + [root / "assessment_test" / lv / sk for lv in LEVELS]:
                if d.is_dir():
                    shutil.rmtree(d)
    for p in parts:
        write_json(part_dir(out, p["skill"], bank_of(p), p["id"]) / "part.json", p)
    summary = reports(parts, res, __import__("pathlib").Path(a.reports))
    s = V.summarise(res)
    print(f"parts: writing={summary['totals']['writing']} speaking={summary['totals']['speaking']}; structural: {summary['structural_validation']}; "
          f"semantic-rule: {summary['semantic_rule_review']}; duplicates confirmed: {summary['duplicates']['confirmed_duplicates']}; bank errors: {len(s['bank_errors'])}")
    return 1 if s["parts_with_errors"] or s["bank_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
