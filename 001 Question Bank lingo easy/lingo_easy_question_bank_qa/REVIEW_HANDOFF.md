# Review handoff

You are an independent reviewer. Everything you need is in this folder; nothing depends on private reasoning.

## Start here (in order)
1. `FINAL_REPORT.md` - what was done, with numerators/denominators.
2. `reports/human_review_queue.csv` - 919 questions with the exact reasons ({'P2': 488, 'P3': 431}).
3. `audit/question_change_log.jsonl` - for each of the 571 edits: original and revised options, fields modified, reason, confidence, timestamp, tool.
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
| 488 distractor rewrites improve plausibility/length parity | **LLM judgement only** - please challenge them |
| CEFR recommendations | heuristic with circular calibration; weak (see `cefr_distribution_before_after.json -> heuristic_vs_recorded_agreement`) |
| Sub-skill classification | rules; `subskill_validation.csv` lists the checks and results |
| Distractor diagnostics | hypotheses; `evidence_class` tells you whether they are text-grounded |
| Blueprint passes | executed on the real assembler (`assembly_simulation_summary.json`) |

Challenge any label by editing the relevant row and re-running the stage that produced it; every stage reads only the bank + config.
Known limitations: `docs/remaining_risks.md`.
