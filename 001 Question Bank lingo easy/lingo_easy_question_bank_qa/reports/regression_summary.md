# Regression summary

Executed by `python -m qa.run_all` (see `validation_commands.log`, `test_results.json`).

* Test command: `python -m unittest discover -s tests -v`  exit status **0**
* Tests run **55**: passed **55**, failed **0**, errors **0**
  * legacy suite `tests/test_pipeline.py`: 19/19 ok
  * QA suite `tests/test_qa.py`: 36/36 ok

## Previously valid content (regression)
* `test_unchanged_questions_identical_and_changed_only_in_distractors`: every one of the 1610 questions keeps id, uuid, prompt, answer letter, answer text, evidence, level and tag;
  488 questions differ from the baseline snapshot **only in distractor texts** (all logged); the rest are byte-identical in these fields; passage/transcript text unchanged for all parts.
* `scripts/validate_part.py --bank question_bank`: exit 0 for all banks (placement + six assessment banks).

## Tests that were modified
* `tests/test_pipeline.py`: two `api.Settings(...)` calls in the demo-bank fixtures now pass `enforce_blueprint=False` (demo bank = 4-item clones that cannot satisfy the production blueprint).
  These tests check API/HTTP plumbing, not blueprint compliance; blueprint behaviour is covered by `tests/test_qa.py`. No assertion was weakened.

## Defects found by the tests during this work (and fixed in code, not in tests)
* `assembler/blueprint.py`: `max_parts_per_topic = 0` was ignored (falsy check).
* `qa/stage3_semantic.py`: number parser double-counted compound numbers ("twenty-four" -> 24 and 4), mis-parsed "five thousand eight hundred", and ignored ordinals ("fifth"); a regex bug also hid all digit-based number checks until this was fixed.
