# Schema migration log

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
