"""Stage 11: compute final metrics, write README / REVIEW_HANDOFF / FINAL_REPORT / remaining_risks / regression summary, copy the corrected
bank + code into the deliverable folder, and build the ZIP.  Run AFTER qa.run_all."""
import csv
import json
import shutil
import statistics
import zipfile
from collections import Counter

from .common import *  # noqa: F401,F403
from . import stage3_semantic as S3
from .stage1_inventory_integrity import question_records

R = REPORTS


def rj(name):
    return json.loads((R / name).read_text(encoding="utf-8"))


def rc(name):
    return list(csv.DictReader(open(R / name, encoding="utf-8-sig")))


def pct(n, d):
    return f"{n}/{d} = {100 * n / d:.1f}%" if d else f"{n}/{d}"


def baseline_entries():
    z = zipfile.ZipFile(OUT / "baseline" / "original_snapshot_before_qa.zip")
    out = []
    for name in z.namelist():
        if name.startswith("question_bank/") and name.endswith("part.json"):
            parts = name.split("/")
            bank = "placement" if parts[1] in ("listening", "reading") else "assessment_" + parts[2]
            out.append({"rel": name, "bank": bank, "part": json.loads(z.read(name))})
    return out


def flag_stats(entries):
    byid = {e["part"]["id"]: e["part"] for e in entries}
    recs = question_records(entries)
    c, longest, n_mc = Counter(), 0, 0
    major_items = 0
    for r in recs:
        rv = S3.review(r, byid[r["part_id"]])
        for f in rv["findings"]:
            if f["severity"] == "major":
                c[f["code"]] += 1
        major_items += any(f["severity"] == "major" for f in rv["findings"])
        if r["question_type"] in ("multiple_choice", "sentence_completion"):
            n_mc += 1
            longest += len(r["answer_text"]) == max(len(o) for o in r["options"])
    return {"major_flag_counts": dict(c), "questions_with_major_flag": major_items, "mc_items": n_mc, "key_is_longest_option": longest}


def main():
    inv = rj("inventory.json")
    nq = inv["counts"]["questions"]
    integ = rc("integrity_findings.csv")
    hard = sum(1 for x in integ if x["severity"] == "hard")
    sem = [json.loads(l) for l in open(R / "semantic_review.jsonl", encoding="utf-8")]
    st = Counter(s["semantic_status"] for s in sem)
    cefr = rj("cefr_distribution_before_after.json")
    cefr_rows = rc("cefr_reassessment.csv")
    skm = rc("skill_tag_mapping.csv")
    subv = rc("subskill_validation.csv")
    diag = rj("distractor_diagnostics_summary.json")
    sim = rj("assembly_simulation_summary.json")
    tests = rj("test_results.json")
    queue = rc("human_review_queue.csv")
    changes = [json.loads(l) for l in open(AUDIT / "question_change_log.jsonl", encoding="utf-8")]
    changed_q = {c["question_id"] for c in changes}
    before = flag_stats(baseline_entries())
    after = flag_stats(load_parts())
    meta = json.loads((ROOT / "config" / "question_meta_v2.json").read_text(encoding="utf-8"))["questions"]
    subskills = Counter(m["primary_subskill"] for m in meta.values())
    inconsistent_tags = Counter((x["modality"], x["original_tag"]) for x in subv if x["result"] == "inconsistent")
    q_inconsistent = len({x["question_id"] for x in subv if x["result"] == "inconsistent"})
    audio_missing = sum(1 for x in rc("asset_reference_audit.csv") if x["asset_type"] == "audio" and x["exists"] == "False")
    placement = sim["results"]["placement"]
    total_runs = sum(r["enforced"]["seeds_executed"] for r in sim["results"].values())
    total_pass = sum(r["enforced"]["exams_passing_all_blueprint_constraints"]["numerator"] for r in sim["results"].values())
    base_pass = sum(r["baseline_no_enforcement"]["exams_passing_all_blueprint_constraints"]["numerator"] for r in sim["results"].values())
    fails = sum(r["enforced"]["generation_failures"] for r in sim["results"].values())
    meaningful = diag["distractors_meaningful_text_grounded_medium_or_high"]
    m = {
        "questions_inspected": nq, "parts_inspected": inv["counts"]["parts"], "integrity_findings_total": len(integ), "integrity_hard_failures": hard,
        "semantic_status": dict(st), "questions_changed": len(changed_q), "change_log_entries": len(changes), "human_review_queue": len(queue),
        "queue_by_priority": dict(Counter(x["priority"] for x in queue)),
        "cefr_recommended_changes_any_gap": cefr["changes_recommended"], "cefr_gap_ge_2": cefr["human_review_required_gap_ge_2"], "cefr_agreement": cefr["heuristic_vs_recorded_agreement"],
        "primary_subskill_counts": dict(subskills), "questions_with_inconsistent_subskill_tag": q_inconsistent,
        "distractors_total": diag["distractors_total"], "distractors_meaningful": meaningful,
        "simulation": {"seeds_per_type": sim["seeds_per_exam_type_and_mode"], "enforced_pass": total_pass, "enforced_runs": total_runs, "baseline_pass": base_pass, "failures": fails},
        "tests": {k: tests[k] for k in ("tests_run", "passed", "failed", "errors", "exit_status")},
        "flags_before": before, "flags_after": after, "audio_missing": audio_missing,
    }
    write_json(R / "final_metrics.json", m)
    # ---------------------------------------------------------------- regression summary
    legacy = [t for t in tests["tests"] if t["test"].startswith("test_pipeline")]
    qa_t = [t for t in tests["tests"] if t["test"].startswith("test_qa")]
    (R / "regression_summary.md").write_text(f"""# Regression summary

Executed by `python -m qa.run_all` (see `validation_commands.log`, `test_results.json`).

* Test command: `{tests['command']}`  exit status **{tests['exit_status']}**
* Tests run **{tests['tests_run']}**: passed **{tests['passed']}**, failed **{tests['failed']}**, errors **{tests['errors']}**
  * legacy suite `tests/test_pipeline.py`: {sum(1 for t in legacy if t['outcome'] == 'ok')}/{len(legacy)} ok
  * QA suite `tests/test_qa.py`: {sum(1 for t in qa_t if t['outcome'] == 'ok')}/{len(qa_t)} ok

## Previously valid content (regression)
* `test_unchanged_questions_identical_and_changed_only_in_distractors`: every one of the {nq} questions keeps id, uuid, prompt, answer letter, answer text, evidence, level and tag;
  {len(changed_q)} questions differ from the baseline snapshot **only in distractor texts** (all logged); the rest are byte-identical in these fields; passage/transcript text unchanged for all parts.
* `scripts/validate_part.py --bank question_bank`: exit 0 for all banks (placement + six assessment banks).

## Tests that were modified
* `tests/test_pipeline.py`: two `api.Settings(...)` calls in the demo-bank fixtures now pass `enforce_blueprint=False` (demo bank = 4-item clones that cannot satisfy the production blueprint).
  These tests check API/HTTP plumbing, not blueprint compliance; blueprint behaviour is covered by `tests/test_qa.py`. No assertion was weakened.

## Defects found by the tests during this work (and fixed in code, not in tests)
* `assembler/blueprint.py`: `max_parts_per_topic = 0` was ignored (falsy check).
* `qa/stage3_semantic.py`: number parser double-counted compound numbers ("twenty-four" -> 24 and 4), mis-parsed "five thousand eight hundred", and ignored ordinals ("fifth"); a regex bug also hid all digit-based number checks until this was fixed.
""", encoding="utf-8")
    # ---------------------------------------------------------------- remaining risks
    (OUT / "docs" / "remaining_risks.md").write_text(f"""# Remaining risks and limitations

1. **No learner-response data.** Difficulty, CEFR level, discrimination and distractor attractiveness are all unmeasured. Every CEFR label is the author's intent; the QA heuristic agrees exactly with it for only {pct(round(cefr['heuristic_vs_recorded_agreement']['exact_agreement'] * nq), nq)} of questions (within one level {100 * cefr['heuristic_vs_recorded_agreement']['within_one_level']:.0f}%, Spearman {cefr['heuristic_vs_recorded_agreement']['spearman_score_vs_recorded_band']}); that disagreement is noise-dominated and must not be read as "the labels are wrong".
2. **Single-model authoring and review.** The bank, the distractor rewrites and the manual false-positive overrides were all produced by the same LLM. Nothing has been checked by a human or a second independent system; all {len(changed_q)} rewritten questions are in the P2 queue.
3. **Residual answer-position cues.** After rewriting, the key is still the longest option in {after['key_is_longest_option']}/{after['mc_items']} plain-MC items ({100 * after['key_is_longest_option'] / after['mc_items']:.0f}%; chance is about 33%, before the rewrite {100 * before['key_is_longest_option'] / before['mc_items']:.0f}%). A learner who always picks the longest option still gains an advantage.
4. **Thin sub-skill coverage.** Primary sub-skills: {', '.join(f'{k} {v}' for k, v in sorted(subskills.items(), key=lambda kv: -kv[1]))}. Inference, main idea and discourse structure cannot support sub-skill claims; A1/A2 listening is detail retrieval only.
5. **Placement extremes.** A placement exam contains only 3 A1 and 3-7 C2 questions; that is presence, not reliable measurement. Level exams are strictly level-pure by assumption; a "target level plus adjacent items" design would need new parts.
6. **Blueprint constraints are mostly satisfied by construction.** Assessment exams violated no constraint even without enforcement; the enforcement only changes placement (topic repetition). Stronger constraints need a bigger bank.
7. **Text length.** Passages are 120-760 words; reading passages are far shorter than IELTS (about 150-500). Lower bounds in `config/blueprint.json` profiles were relaxed to fit the authored texts; this was a content decision, not a measurement one.
8. **No audio.** {audio_missing} listening parts reference mp3 files that do not exist; transcripts and audio cannot be cross-checked and the construct changes (reading a transcript).
9. **Rule-based semantics.** The semantic review is lexical/structural. It cannot prove that an item is valid; passing it means "no rule fired". Evidence quotes exist in the source but may not entail the key.
10. **Diagnostics are hypotheses.** Only {pct(meaningful, diag['distractors_total'])} distractors have a text-grounded, medium-confidence explanation; none are validated.
11. **Learning objectives are placeholders** (generated sub-skill x level strings). Lesson mapping is empty because no lesson bank exists in the project.
12. **Question status.** All content is `validated` (script) - none is `reviewed`/`approved`. `--stamp` re-validated edited parts automatically.
13. **Duplicate detection** found no near-duplicate questions or sources at the chosen thresholds (prompt+key Jaccard >= 0.75, 5-gram source overlap >= 0.15); this is a statement about those thresholds only. `reports/duplicate_candidates.csv` is therefore header-only.
14. **Pass mark and indicative-level rules** (60 %) are prototype values taken from the project, not validated.
""", encoding="utf-8")
    # ---------------------------------------------------------------- schema migration log
    (AUDIT / "schema_migration_log.md").write_text("""# Schema migration log

| # | Change | Type | Breaking? | Reversible |
|---|---|---|---|---|
| 1 | part.json (v1) content unchanged in shape; distractor texts of 488 questions edited (571 log entries), `derived.content_hash` of edited parts recomputed by `--stamp` | content | no | yes (original in `baseline/original_snapshot_before_qa.zip`, edits in `question_change_log.jsonl`) |
| 2 | New sidecars `config/question_meta_v2.json`, `config/distractor_diagnostics_v2.json` (keyed by question UUID) | additive | no | delete files |
| 3 | New `config/exam_blueprint_v1.json` + `assembler/blueprint.py`; `assemble(..., enforce_blueprint=True, blueprint_path=None, meta=None)` | additive API | **behaviour**: standard-count exams can now fail with `BlueprintError` instead of being returned unchecked | set `enforce_blueprint=False` / `LINGO_ENFORCE_BLUEPRINT=0` |
| 4 | Stored exam gains `blueprint{}` and per-key `question_uuid, part_uuid, part_content_hash, option_origin, shown_options` | additive | no (old readers ignore new keys) | n/a |
| 5 | `server/api.py`: `Settings.enforce_blueprint`; 409 body may be an object `{error,message,details}`; `submit_exam` also writes `<exam_id>.attempt.json` | additive/behaviour | frontend updated to read `detail.message` | yes |
| 6 | Option order is shuffled per exam (done in the previous work item) and now recorded (`option_origin`) | behaviour | no | n/a |
| 7 | v2 export `exports/question_records_v2.jsonl` + `schemas/question_schema_v2.json` | additive | no | delete |
| 8 | Profiles `level_a1..level_c2` added to `config/blueprint.json`, schema enum extended (previous work item) | additive | no | |
""", encoding="utf-8")
    # ---------------------------------------------------------------- copies
    dst = OUT / "corrected_bank"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(BANK, dst / "question_bank", ignore=shutil.ignore_patterns("__pycache__"))
    code = OUT / "code"
    if code.exists():
        shutil.rmtree(code)
    for d in ("assembler", "adaptive", "qa", "server", "scripts", "tests", "frontend"):
        shutil.copytree(ROOT / d, code / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("config/blueprint.json", "config/taxonomy.json", "config/exam_blueprint_v1.json", "config/question_meta_v2.json", "config/distractor_diagnostics_v2.json", "schemas/part.schema.json", "README.md", "requirements.txt"):
        (code / Path(f).parent).mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, code / f)
    (OUT / "README.md").write_text(readme(m), encoding="utf-8")
    (OUT / "REVIEW_HANDOFF.md").write_text(handoff(m), encoding="utf-8")
    (OUT / "FINAL_REPORT.md").write_text(final_report(m, cefr, diag, skm, inconsistent_tags, sim, tests), encoding="utf-8")
    # zip
    zp = ROOT / "lingo_easy_question_bank_qa.zip"
    if zp.exists():
        zp.unlink()
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(ROOT).as_posix())
    print("zip", zp.stat().st_size, "bytes;", json.dumps(m)[:200])
    return m


def readme(m):
    return f"""# Lingo Easy - question bank QA deliverable

Generated by `python -m qa.run_all` + `python -m qa.stage11_package` from the real project at `D:\\001 Question Bank lingo easy`.
{m['questions_inspected']} questions in {m['parts_inspected']} parts were inspected (placement bank + six level-assessment banks).

## What is in this folder
| Path | Content |
|---|---|
| `baseline/` | pre-QA snapshot (zip) + SHA-256 of 160 files (project is not a git repo, so this is the backup) |
| `corrected_bank/question_bank/` | the corrected bank in its original (v1) format |
| `code/` | modified/added code: `assembler/` (blueprint-aware), `adaptive/`, `qa/` (pipeline), `server/`, `tests/` (incl. `test_qa.py`), `config/` sidecars |
| `blueprints/exam_blueprint_v1.json` | explicit blueprints for placement and A1..C2 assessments |
| `schemas/` | `question_schema_v2`, `learner_attempt_schema`, `adaptive_profile_schema`, `skill_taxonomy` |
| `reports/` | inventory, integrity, duplicates, assets, semantic review, CEFR, taxonomy, diagnostics, simulation, tests, review queue, final metrics |
| `audit/` | `question_change_log.jsonl` (original + revised content per change), summary CSV, schema migration log |
| `exam_manifests/` | one CSV per exam type: seed, selected parts, level counts, attempts, violations for every generated exam |
| `exports/question_records_v2.jsonl` | flat v2 view of every question (+ diagnostics) |
| `docs/` | adaptive spec, schema decisions, remaining risks, synthetic example profiles |
| `FINAL_REPORT.md`, `REVIEW_HANDOFF.md` | executive answers; instructions for the independent reviewer |

## Reproduce
```
python -m qa.apply_patches          # idempotent; applies only patches listed as not yet applied
python -m qa.run_all 1000           # all stages + tests, logs commands and exit codes
python -m qa.stage11_package        # reports, docs, copies, zip
```

## Honest scope statement
* **Automated validation** (real, executed): integrity, rule-based semantic checks, blueprint checks, 1,000-seed assembler simulations per exam type, unit tests.
* **LLM-assisted work** (same model that wrote the bank): the {m['questions_changed']} distractor rewrites and the manual false-positive overrides. Not independent.
* **Human review:** none has taken place. **Empirical learner testing:** none.
* Not produced as a real result: `duplicate_candidates.csv` and `assembly_failures.csv` contain only a header row because the checks found nothing (that is the result, not a placeholder).
* CEFR and sub-skill outputs are recommendations; **no `level.cefr`, `skill_tag`, answer key, id or uuid was changed in the bank.**
"""


def handoff(m):
    return f"""# Review handoff

You are an independent reviewer. Everything you need is in this folder; nothing depends on private reasoning.

## Start here (in order)
1. `FINAL_REPORT.md` - what was done, with numerators/denominators.
2. `reports/human_review_queue.csv` - {m['human_review_queue']} questions with the exact reasons ({m['queue_by_priority']}).
3. `audit/question_change_log.jsonl` - for each of the {m['change_log_entries']} edits: original and revised options, fields modified, reason, confidence, timestamp, tool.
4. `blueprints/exam_blueprint_v1.json` + `exam_manifests/manifest_*.csv` + `reports/assembly_simulation_summary.json` - seeds and results of the multi-seed audit.
5. `docs/remaining_risks.md`, `docs/schema_decisions.md`, `docs/adaptive_learning_diagnostic_spec.md`.

## Reconstruct a single question
`reports/inventory.json` -> record by `question_id` (source file, part, level, tag, options, evidence, explanation) ->
`corrected_bank/question_bank/.../part.json` (current text, includes the whole passage/transcript) ->
`baseline/original_snapshot_before_qa.zip` (original) -> `audit/question_change_log.jsonl` (change) -> `reports/semantic_review.jsonl`, `reports/cefr_reassessment.csv`,
`reports/subskill_validation.csv`, `reports/distractor_diagnostics.csv` (all keyed by `question_id` and `uuid`) -> `exports/question_records_v2.jsonl` (everything in one record).

## Reproduce the checks
```
python scripts/validate_part.py --bank question_bank
python -m unittest discover -s tests -v
python -m qa.stage1_inventory_integrity     # independent integrity checks
python -m qa.stage8_simulation 1000         # assembler distribution audit (real assembler)
```
File checksums: `reports/inventory.json -> file_hashes_sha256` (current) and `baseline/hashes_before.json` (before).

## What you can and cannot trust
| Claim | Basis |
|---|---|
| Ids, uuids, keys, source texts unchanged | executed regression test against the baseline snapshot |
| Evidence quotes exist in sources | executed check (existence only, not entailment) |
| {m['questions_changed']} distractor rewrites improve plausibility/length parity | **LLM judgement only** - please challenge them |
| CEFR recommendations | heuristic with circular calibration; weak (see `cefr_distribution_before_after.json -> heuristic_vs_recorded_agreement`) |
| Sub-skill classification | rules; `subskill_validation.csv` lists the checks and results |
| Distractor diagnostics | hypotheses; `evidence_class` tells you whether they are text-grounded |
| Blueprint passes | executed on the real assembler (`assembly_simulation_summary.json`) |

Challenge any label by editing the relevant row and re-running the stage that produced it; every stage reads only the bank + config.
Known limitations: `docs/remaining_risks.md`.
"""


def final_report(m, cefr, diag, skm, inconsistent_tags, sim, tests):
    n = m["questions_inspected"]
    st = m["semantic_status"]
    s = m["simulation"]
    fl_b, fl_a = m["flags_before"], m["flags_after"]
    tag_lines = "\n".join(f"  - `{mod}:{tag}`: {c} questions fail an automated consistency check" for (mod, tag), c in inconsistent_tags.most_common())
    mapping_lines = "\n".join(f"  - `{x['modality']}:{x['original_tag']}` ({x['items_using_tag']} items): {x['issue']}" for x in skm if x["issue"])
    sim_lines = "\n".join(f"  - {k}: enforced {v['enforced']['exams_passing_all_blueprint_constraints']['numerator']}/{s['seeds_per_type']}; no enforcement {v['baseline_no_enforcement']['exams_passing_all_blueprint_constraints']['numerator']}/{s['seeds_per_type']}" for k, v in sim["results"].items())
    return f"""# Final report

Separate evidence classes: **A** automated validation (executed) | **B** LLM-assisted work (same model as the author; not independent) | **C** human review (none yet) | **D** learner data (none).

## Direct answers

1. **Questions inspected:** {n} in {m['parts_inspected']} parts (A).
2. **Semantically valid without changes:** {pct(st.get('pass', 0), n)} passed all automated rule checks with no edit - this is *"no rule fired"*, not validation of meaning (A).
3. **Corrected:** {pct(m['questions_changed'], n)} questions had distractors rewritten ({m['change_log_entries']} log entries over 3 passes); answer keys, prompts, evidence, levels, tags, ids and uuids untouched (B, with A regression test).
4. **Need human review:** {m['human_review_queue']} in `human_review_queue.csv` ({m['queue_by_priority']}). P2 = every rewritten question, P3 = heuristic signals.
5. **CEFR changes recommended:** {m['cefr_recommended_changes_any_gap']}/{n} differ by at least one level and {m['cefr_gap_ge_2']}/{n} by two or more; **none applied.** The heuristic matches recorded levels exactly for {100 * m['cefr_agreement']['exact_agreement']:.1f}% (within one level {100 * m['cefr_agreement']['within_one_level']:.1f}%, Spearman {m['cefr_agreement']['spearman_score_vs_recorded_band']}), so it is only an outlier detector (A, circular calibration).
6. **Skill tags inconsistent or misleading:** (A)
{mapping_lines}
{tag_lines}
   {m['questions_with_inconsistent_subskill_tag']}/{n} questions fail at least one automated tag check. Largest gaps in the bank: {', '.join(f'{k} {v}' for k, v in sorted(m['primary_subskill_counts'].items(), key=lambda kv: -kv[1]))}.
7. **Distractors with meaningful diagnostic explanations:** {pct(m['distractors_meaningful'], m['distractors_total'])} (definition: text-grounded + medium/high confidence + quoted evidence); all are hypotheses (A/B).
8. **Generated exams passing all blueprint constraints (real assembler, {s['seeds_per_type']} seeds per type, 7 exam types):** {pct(s['enforced_pass'], s['enforced_runs'])} with enforcement; {pct(s['baseline_pass'], s['enforced_runs'])} without it (legacy behaviour). Method: each returned exam is re-validated independently by `validate_exam`; failures to generate count as failures.
{sim_lines}
9. **Remaining generation failures:** {s['failures']} (see `reports/assembly_failures.csv`). Residual risk is bank coverage, not the algorithm: see `docs/remaining_risks.md` (item 5 and 6).
10. **Schema fields:** added (sidecars, v2 export, attempt and profile schemas, stored-exam fields), retained all v1 fields, **deprecated (recommended)** `skill_tag` as analytics dimension and the overloaded `profile`, **removed none** (`docs/schema_decisions.md`).
11. **Tests:** {m['tests']['tests_run']} run, {m['tests']['passed']} passed, {m['tests']['failed']} failed, {m['tests']['errors']} errors, exit {m['tests']['exit_status']} (`reports/test_results.json`, `reports/regression_summary.md`).
12. **Uncertain without learner data:** item difficulty and CEFR labels, discrimination, whether distractors attract the hypothesised errors, reliability of 3-item level slices (A1/C2 in placement), the 60% pass mark and indicative-level rule, and all adaptive-profile thresholds.

## What the QA found and fixed (before -> after, same checker, A)
* Key is the longest option in plain MC items: {fl_b['key_is_longest_option']}/{fl_b['mc_items']} -> {fl_a['key_is_longest_option']}/{fl_a['mc_items']}.
* Questions with a major rule flag: {fl_b['questions_with_major_flag']} -> {fl_a['questions_with_major_flag']}. Flags before: {fl_b['major_flag_counts']}. After: {fl_a['major_flag_counts']}.
* Defects in the delivery code found by the new tests (fixed): blueprint falsy check, number parser, digit regex (details in `reports/regression_summary.md`).

## Completed vs only recommended vs not done
* **Completed:** inventory, integrity, rule-based semantic review, distractor rewrites with audit trail, CEFR heuristic, taxonomy + validation, diagnostics, schemas, blueprint + enforced assembler, 7 x {s['seeds_per_type']}-seed simulations (x2 modes), attempt recording, adaptive profile code with synthetic examples, tests, packaging.
* **Only recommended:** CEFR changes, tag changes, `profile` split, per-item versioning, forbidden-pair list population, lesson mapping.
* **Not done / not possible here:** human or second-model review, learner calibration, audio verification (no audio), semantic validation of every question by an independent reader.
"""


if __name__ == "__main__":
    main()
