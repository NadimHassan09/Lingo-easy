# Final report

Separate evidence classes: **A** automated validation (executed) | **B** LLM-assisted work (same model as the author; not independent) | **C** human review (none yet) | **D** learner data (none).

## Direct answers

1. **Questions inspected:** 1610 in 140 parts (A).
2. **Semantically valid without changes:** 1122/1610 = 69.7% passed all automated rule checks with no edit - this is *"no rule fired"*, not validation of meaning (A).
3. **Corrected:** 488/1610 = 30.3% questions had distractors rewritten (571 log entries over 3 passes); answer keys, prompts, evidence, levels, tags, ids and uuids untouched (B, with A regression test).
4. **Need human review:** 919 in `human_review_queue.csv` ({'P2': 488, 'P3': 431}). P2 = every rewritten question, P3 = heuristic signals.
5. **CEFR changes recommended:** 1093/1610 differ by at least one level and 448/1610 by two or more; **none applied.** The heuristic matches recorded levels exactly for 32.1% (within one level 72.2%, Spearman 0.649), so it is only an outlier detector (A, circular calibration).
6. **Skill tags inconsistent or misleading:** (A)
  - `listening:gist` (9 items): 1 of 9 items fail an automated consistency check
  - `listening:specific_detail` (234 items): 10 of 234 items fail an automated consistency check
  - `listening:numbers_dates_times` (152 items): Tag describes a content/answer type, not a sub-skill: Describes the kind of answer (numeric), not a separate skill.
  - `listening:speaker_opinion` (5 items): 1 of 5 items fail an automated consistency check
  - `listening:speaker_attitude` (32 items): 5 of 32 items fail an automated consistency check
  - `listening:purpose` (0 items): unused in the current bank
  - `listening:inference` (17 items): 4 of 17 items fail an automated consistency check
  - `listening:sequence` (0 items): unused in the current bank
  - `listening:paraphrase_recognition` (39 items): 26 of 39 items fail an automated consistency check
  - `listening:distractor_resolution` (211 items): Tag describes a item-construction feature / test-taking strategy, not a sub-skill: Describes how the item is built (a corrected/rejected option), not a language skill.
  - `listening:organisation_signposting` (1 items): Tag describes a linguistic feature, not a sub-skill: 
  - `reading:specific_detail` (341 items): 12 of 341 items fail an automated consistency check
  - `reading:writer_claim` (109 items): 18 of 109 items fail an automated consistency check
  - `reading:fact_check` (235 items): Tag describes a question format, not a sub-skill: Describes the True/False/Not Given format.
  - `reading:vocabulary_in_context` (0 items): unused in the current bank
  - `reading:reference_resolution` (0 items): unused in the current bank
  - `reading:paraphrase_matching` (116 items): 4 of 116 items fail an automated consistency check
  - `reading:heading_matching` (0 items): Tag describes a question format, not a sub-skill: Describes the matching-headings format; not used. | unused in the current bank
  - `reading:summary_gap` (96 items): Tag describes a question format, not a sub-skill: Used for sentence-completion items; the format, not a skill.
  - `listening:distractor_resolution`: 91 questions fail an automated consistency check
  - `listening:paraphrase_recognition`: 26 questions fail an automated consistency check
  - `reading:writer_claim`: 18 questions fail an automated consistency check
  - `reading:specific_detail`: 12 questions fail an automated consistency check
  - `listening:specific_detail`: 10 questions fail an automated consistency check
  - `listening:speaker_attitude`: 5 questions fail an automated consistency check
  - `listening:numbers_dates_times`: 4 questions fail an automated consistency check
  - `listening:inference`: 4 questions fail an automated consistency check
  - `reading:paraphrase_matching`: 4 questions fail an automated consistency check
  - `listening:gist`: 1 questions fail an automated consistency check
  - `listening:speaker_opinion`: 1 questions fail an automated consistency check
   176/1610 questions fail at least one automated tag check. Largest gaps in the bank: detail_retrieval 823, claim_verification 235, information_tracking 211, paraphrase_recognition 155, stance_attitude 146, inference 23, main_idea_gist 12, discourse_structure 5.
7. **Distractors with meaningful diagnostic explanations:** 541/3329 = 16.3% (definition: text-grounded + medium/high confidence + quoted evidence); all are hypotheses (A/B).
8. **Generated exams passing all blueprint constraints (real assembler, 1000 seeds per type, 7 exam types):** 7000/7000 = 100.0% with enforcement; 6880/7000 = 98.3% without it (legacy behaviour). Method: each returned exam is re-validated independently by `validate_exam`; failures to generate count as failures.
  - placement: enforced 1000/1000; no enforcement 880/1000
  - assessment_A1: enforced 1000/1000; no enforcement 1000/1000
  - assessment_A2: enforced 1000/1000; no enforcement 1000/1000
  - assessment_B1: enforced 1000/1000; no enforcement 1000/1000
  - assessment_B2: enforced 1000/1000; no enforcement 1000/1000
  - assessment_C1: enforced 1000/1000; no enforcement 1000/1000
  - assessment_C2: enforced 1000/1000; no enforcement 1000/1000
9. **Remaining generation failures:** 0 (see `reports/assembly_failures.csv`). Residual risk is bank coverage, not the algorithm: see `docs/remaining_risks.md` (item 5 and 6).
10. **Schema fields:** added (sidecars, v2 export, attempt and profile schemas, stored-exam fields), retained all v1 fields, **deprecated (recommended)** `skill_tag` as analytics dimension and the overloaded `profile`, **removed none** (`docs/schema_decisions.md`).
11. **Tests:** 55 run, 55 passed, 0 failed, 0 errors, exit 0 (`reports/test_results.json`, `reports/regression_summary.md`).
12. **Uncertain without learner data:** item difficulty and CEFR labels, discrimination, whether distractors attract the hypothesised errors, reliability of 3-item level slices (A1/C2 in placement), the 60% pass mark and indicative-level rule, and all adaptive-profile thresholds.

## What the QA found and fixed (before -> after, same checker, A)
* Key is the longest option in plain MC items: 795/1152 -> 594/1152.
* Questions with a major rule flag: 488 -> 0. Flags before: {'length_cue_correct_option_longest': 473, 'extreme_wording_in_distractor': 52}. After: {}.
* Defects in the delivery code found by the new tests (fixed): blueprint falsy check, number parser, digit regex (details in `reports/regression_summary.md`).

## Completed vs only recommended vs not done
* **Completed:** inventory, integrity, rule-based semantic review, distractor rewrites with audit trail, CEFR heuristic, taxonomy + validation, diagnostics, schemas, blueprint + enforced assembler, 7 x 1000-seed simulations (x2 modes), attempt recording, adaptive profile code with synthetic examples, tests, packaging.
* **Only recommended:** CEFR changes, tag changes, `profile` split, per-item versioning, forbidden-pair list population, lesson mapping.
* **Not done / not possible here:** human or second-model review, learner calibration, audio verification (no audio), semantic validation of every question by an independent reader.
