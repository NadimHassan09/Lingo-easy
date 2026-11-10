# Writing and Speaking in Lingo Easy

Both skills are **productive** skills: one open-ended task per Part, no answer key, many valid responses. They live in the same unified bank as Reading and Listening and use the same
identity and metadata conventions (`id`, `uuid`, `skill`, `part_type`, `title`, `topic`, `profile`, `level {cefr, band}`, `skill_tag`, `meta.status`, `derived.content_hash`).

## Where things are

| What | Where |
|---|---|
| Writing generator skill | `.agent/skills/lingoeasy-writing-generator/SKILL.md` (+ `references/writing-level-matrix.md`) |
| Speaking generator skill | `.agent/skills/lingoeasy-speaking-generator/SKILL.md` (+ `references/speaking-level-matrix.md`) |
| Code that turns a task spec into a full Part | `productive/` (`generate.py`, `build.py`, `validate.py`, `cefr.py`, `criteria_text.py`, `audit.py`, `run_all.py`) |
| Controlled vocabularies, per-level limits, criterion weights, diagnostics | `productive/config/productive_taxonomy.json` (shared lists stay in `config/taxonomy.json`) |
| Authored task specs (the 140 current tasks) | `productive/specs/*.py`; new single tasks: `productive/specs/json/` |
| Content | `question_bank/placement_test/{writing,speaking}/`, `question_bank/assessment_test/<LEVEL>/{writing,speaking}/` |
| Schemas | `schemas/writing_part.schema.json`, `speaking_part.schema.json`, `evaluation_blueprint.schema.json`, `generation_metadata.schema.json`, `productive_attempt.schema.json` (rebuilt by `python -m productive.schemas_build`) |
| Reports and audit | `lingo_easy_writing_speaking/reports/`, `lingo_easy_writing_speaking/AUDIT_REPORT.md` |

## How to generate new Parts

1. Ask an agent that reads `.agent/skills/` (Antigravity, Claude Code ...): *"Use lingoeasy-writing-generator to add a B2 writing part"* (or the speaking one).
   The agent writes a **spec JSON** (fields listed in the SKILL.md) and runs
   `python -m productive.generate --spec-file spec.json --skill writing --bank B2`. The tool picks the next free id, builds the Part (task, expected response, evaluation blueprint,
   diagnostics, difficulty, provenance), validates it, and writes it only when there is no error.
2. Re-run `python -m productive.build` (regenerates the authored pool and all reports) or just `python -m productive.validate` / `python scripts/validate_part.py --bank question_bank`.
3. Counts: a bank of ten tasks per skill and scope is the current contract (`bank_target_parts` in the taxonomy). Adding an eleventh task means updating that number and the placement design.

Generation is deterministic: the same specs and seed give identical Parts (UUIDs derive from the id). No model is called at build time; the specs were authored by an LLM and
the authoring model is recorded in each Part's `provenance`.

## What the Parts contain

`task` (learner-facing) / `expected_response` (content points, required and optional elements, organisation, vocabulary and grammar demands, an *illustrative* outline - never an answer key) /
`classification` (primary and secondary sub-skills, cognitive processes, measurable learning objectives) / `difficulty` (target and heuristic CEFR, confidence, demand, rationale, adjacent-level demands;
`calibrated: false`) / `evaluation_blueprint` (weighted criteria with successful and weak performance, evidence, common errors incl. Arabic-L1 hypotheses, limitations; required, optional and **not penalised**
demonstrations; criteria not assessed by design; evaluator output contract) / `diagnostics` (categories to look for, plus the rule *observed error is not an inferred weakness*) / `qa` / `provenance` (generator, seed, authoring model, hash of the spec and the spec itself).

Learner-facing exam views (`assembler.public_part`) contain only the task fields; level, rubric, diagnostics, outlines and provenance never leave the server.

## Exam assembly

`assemble(scope_dir, ..., writing=None, speaking=None)`: a scope is `placement_test/` or `assessment_test/<LEVEL>/` (`assembler/layout.py`). Defaults come from `config/blueprint.json -> productive`:
placement = 3 tasks per skill, one from each level stratum (easiest first), assessment = 2 tasks per skill, all at the assessment level. Reading/Listening selection for a given seed is unchanged by the
new skills (separate random stream) and the existing blueprint is applied to the multiple-choice parts only. A scope with no Writing/Speaking parts silently keeps working as before (the section is omitted and a note is stored).

## Responses and the current MVP

* Writing: textarea, saved as `typed_text`. Speaking: a **simulated** microphone button (no microphone access, no recording, no upload, no speech recognition) and a transcript box that the learner can type into;
  saved as `manual_transcript` with `transcript_source: "manual_entry"`.
* `POST /api/exam/{id}/submit` accepts `{"answers": {...}, "responses": {"<part_id>": {"text": "...", "input_method": "..."}}, "learner_id": "..."}`.
  Stored: `<exam_id>.result.json` (responses included), `<exam_id>.responses.json` (one record per task, `schemas/productive_attempt.schema.json`, empty text for skipped tasks, `evaluation_status: "not_evaluated"`).
* Writing and Speaking are **not scored** in this version; the numeric score and the indicative level cover the multiple-choice questions only, and the result screen says so.
* Pronunciation is never assessed from text. The blueprints mark `S_PRON` as not assessable and `S_FC` as partial.

## Where audio, STT and evaluation will plug in (not implemented)

1. Front end: replace the simulated button with real capture; the transcript box then receives STT output and the request sends `input_method: "stt_transcript"` (currently rejected by the API on purpose).
2. Storage: the optional `audio_extension` block (audio reference, duration, transcript, STT provider/confidence, pronunciation/fluency evaluation) already exists in the speaking schema and in `productive_attempt.schema.json`.
3. Evaluation: a worker reads `<exam_id>.responses.json` + each Part's `evaluation_blueprint` and writes the `evaluation` object described by `evaluator_output_contract`; learner-profile updates can reuse `diagnostics.targets`.

## Limits you should know

CEFR labels are authored intent plus an uncalibrated heuristic; no human has reviewed any Part (`qa.human_review: "not_reviewed"`); placement has one A1 and one C2 task per skill, so the extremes are thin;
a placement exam shows three tasks per skill; topic coverage and sub-skill coverage are broad but each combination has very few tasks. See `lingo_easy_writing_speaking/AUDIT_REPORT.md`.
