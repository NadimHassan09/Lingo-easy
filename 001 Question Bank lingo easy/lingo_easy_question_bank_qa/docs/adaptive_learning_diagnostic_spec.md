# Adaptive learning diagnostic specification (v1.0)

Status: **implemented and unit-tested on synthetic data only.** No real learner responses exist, so no part of this
specification has been calibrated or validated against learners.

## 1. Data separation

| Layer | Where it lives | Mutable by learners? | Contents |
|---|---|---|---|
| Authoritative question content | `question_bank/**/part.json` (schema v1, unchanged) | no | passages/transcripts, items, keys, evidence, original level and tag |
| Static question metadata | `config/question_meta_v2.json`, `config/distractor_diagnostics_v2.json` (generated sidecars, keyed by question UUID) | no | primary/secondary sub-skill, cognitive process, answer type, distractor hypotheses |
| Exam assembly | `exams/<exam_id>.json` | written once per exam | seed, parts, blueprint status, answer key incl. shown-option -> bank-option map |
| Learner attempt data | `exams/<exam_id>.attempt.json` today (DB table in production), schema `schemas/learner_attempt_schema.json` | yes | one record per question per attempt |
| Adaptive profile | derived by `adaptive/profile.py`, schema `schemas/adaptive_profile_schema.json` | derived | claims with supporting `attempt_record_id`s |

A learner's responses are **never** written into a question record (tested by `test_no_learner_data_in_bank`).

## 2. What is recorded for every answer attempt

`adaptive/attempts.py::build_attempt_records` produces, per question: question id + uuid + `question_version` (the part's content hash at assembly time), selected option
(as shown, and the bank's letter for the same option because options are shuffled per exam), correctness, primary/secondary sub-skills, learning-objective ids, the distractor
diagnostic of the chosen option (error tags, confidence, evidence class, provenance string), response time when supplied, assessment id, attempt id, source/part ids.
`server/api.py::submit_exam` writes this file next to the stored exam; a failure to write never blocks scoring.

## 3. From attempts to a profile

`adaptive/profile.py::build_profile(learner_id, {attempt_id: records})`.

* **Observed performance** - answered/correct/accuracy with a 95 % Wilson interval overall, per modality and per primary sub-skill.
* **Estimated proficiency (CEFR)** - kept separate from sub-skill mastery. Rule: the last CEFR level, in order, with >= 60 % correct on >= 4 answered items, stopping at the first level
  below the threshold; levels with fewer than 4 items are skipped. Always labelled `indicative`; confidence label is `insufficient_evidence`, `low` (< 20 items used) or `moderate`.
* **Sub-skill status** - `insufficient_evidence` (< 6 answered), `weakness` (Wilson upper bound < 0.60), `strength` (Wilson lower bound > 0.60), otherwise `typical_or_unclear`.
  One wrong answer can therefore never produce a weakness.
* **Profile status** - `insufficient_evidence` (< 6 answered), `provisional` (< 2 attempts or < 40 answered), `established_for_this_instrument` otherwise. "Established" means
  "enough data under these rules", not "calibrated".
* **Consistency** - needs >= 2 attempts with >= 10 answers; `consistent` if the accuracy spread <= 0.15.
* **Error patterns** - an error tag is reported only after >= 3 occurrences, with how many of them are `text_grounded`; `weak_hypothesis` unless >= 3 are text-grounded.
  `insufficient_evidence_to_classify` is never reported as a pattern.
* **Recommended next objectives** - for each weakness: `LO.<subskill>.<current level>` (priority 1); for each strength: the same sub-skill one level up (priority 2). Every
  recommendation carries `evidence_refs`. `lesson_ref` is `null` because no lesson/exercise bank exists in the project.
* **Uncertainty** - three standing caveats are written into every profile (uncalibrated difficulty, thin sub-skill coverage, error patterns are hypotheses).

## 4. How distractor diagnostics are produced and how far to trust them

Per wrong option (`qa/stage6_diagnostics.py`): either `text_grounded` (the option overlaps a specific source sentence, which is quoted in `evidence_basis`) or `item_structure`
(e.g. choosing Not Given when the answer is True). Confidence is categorical and **not calibrated**. In the current bank, only a minority of distractors have a text-grounded,
medium-confidence explanation (see `reports/distractor_diagnostics_summary.json`); the rest carry a generic hypothesis or "insufficient evidence".

## 5. Known gaps that limit adaptive use today

* Item difficulty is the author's label, not measured. Do not use the profile for high-stakes decisions.
* ~51 % of questions are detail retrieval and ~15 % claim verification; inference, main idea and discourse structure have 23, 12 and 5 questions - far too few for sub-skill claims.
* A1/A2 listening contains only detail-retrieval items.
* Learning objectives (`LO.<subskill>.<level>`) are generated placeholders (`schemas/skill_taxonomy.json`), not curriculum-approved can-do statements.
* No audio exists yet: listening is answered from transcripts, which changes what is measured.

## 6. Synthetic examples

`docs/examples/profile_synthetic-*.json` (+ sample attempt records) were generated by `qa/stage9_adaptive_examples.py` from **simulated** learners (logistic response model, seeded).
They demonstrate the schema and rules only.
