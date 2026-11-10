# Lingo Easy: Listening & Reading question-bank generators

Agent skills + config + validator to build the placement-test **Question Bank** (Listening and Reading first).

## Layout

```
config/blueprint.json     counts, profiles (foundation/intermediate/advanced), CEFR<->band ranges, bank targets
config/taxonomy.json      controlled tags: topics, skill_tags, grammar_rules, lexical_types, accents
schemas/part.schema.json  JSON shape of one part
docs/level-calibration.md
.agent/skills/lingoeasy-listening-generator/SKILL.md   (Antigravity workspace skill, auto-discovered)
.agent/skills/lingoeasy-reading-generator/SKILL.md
.agent/skills/lingoeasy-writing-generator/SKILL.md     (open-ended Writing tasks; see docs/productive-skills.md)
.agent/skills/lingoeasy-speaking-generator/SKILL.md    (open-ended Speaking tasks; text-only MVP)
productive/                 generator code, validators, audit and run_all for Writing/Speaking; docs/productive-skills.md
scripts/validate_part.py  validator, --stamp (derived fields + UUIDs), --bank report (no dependencies)
scripts/export_tts_scenario.py  listening part.json -> tts-config.json for the source repo's generate-tts.py (optional Gemini route)
scripts/generate_listening_audio.py  listening part -> mp3 in the part's folder with the free edge-tts service (no API key); see "Listening audio" below
config/tts-base-config.json     copy of the source repo's TTS config (voices, delivery presets)
NOTICE.md                 CC BY 4.0 attribution
examples/                 4-item mini parts (LI001, RE001) for testing the pipeline only
```

## Bank layout (unified, all four skills)

```
question_bank/
  placement_test/{reading,listening,writing,speaking}/<ID>/part.json
  assessment_test/<A1|A2|B1|B2|C1|C2>/{reading,listening,writing,speaking}/<ID>/part.json
```

Reading/Listening ids: `RE001`, `LI001` (placement), `RE1xx`..`RE6xx` / `LI1xx`..`LI6xx` (A1..C2). Writing/Speaking: `WR001`..`WR010`, `SP001`..`SP010` (placement), `WR1xx`..`WR6xx`, `SP1xx`..`SP6xx`.
Path logic lives in one place: `assembler/layout.py`. (Before the four-skill work the bank was `question_bank/{listening,reading}` + `question_bank/assessment/<L>/...`; the pre-change copy is in `backups/`.)

## How to use (AntiGravity / Claude Code / any agent that reads SKILL.md)

1. Put the CONTENTS of this folder at your workspace root. Antigravity auto-discovers workspace skills in `.agent/skills/`.
2. Prompt, e.g.: *"Use lingoeasy-reading-generator to generate RE001-RE010 (3 foundation, 4 intermediate, 3 advanced). Validate each one and stamp it."*
3. Check progress anytime: `python scripts/validate_part.py --bank question_bank`
4. Try the pipeline first: `python scripts/validate_part.py examples/question_bank/reading/RE001/part.json --mini`

## Two test types (placement and assessment)

```
question_bank/placement_test/       placement bank  (Reading/Listening profiles foundation / intermediate / advanced, mixed CEFR levels; Writing/Speaking tasks spread over A1-C2)
question_bank/assessment_test/<LEVEL>/   one bank per CEFR level A1 A2 B1 B2 C1 C2 (10 parts per skill, every item/task of that level only)
```

- **Placement test** (default): 4 Listening + 3 Reading parts of mixed profiles, plus 3 Writing and 3 Speaking tasks (one from each level stratum), indicative level in the result (from the multiple-choice questions).
- **Assessment test**: pick a level (A1..C2) on the home screen; parts come only from `question_bank/assessment_test/<LEVEL>/` (plus 2 Writing and 2 Speaking tasks of that level)
  (profile `level_a1` .. `level_c2` in `config/blueprint.json`). The result is a score plus pass/fail (prototype pass mark 60%).
- API: `POST /api/exam/start` with `{"mode": "placement"}` or `{"mode": "assessment", "level": "B1"}` (optional `listening`, `reading`, `writing`, `speaking` counts);
  `POST /api/exam/{id}/submit` with `{"answers": {...}, "responses": {"<part_id>": {"text": "...", "input_method": "typed_text|manual_transcript"}}}`.
- Writing and Speaking are stored but **not scored** yet; Speaking has a simulated microphone button (no recording, no speech-to-text). Details and future integration points: `docs/productive-skills.md`.
- Randomness per attempt: which parts are drawn, the order of parts inside each skill, and the option order of plain
  multiple-choice items (True/False/Not Given, Yes/No/Not Given and matching items keep their natural order).
  The exam screen has a "Test composition" line that lists the part ids of the current attempt.
- Validate everything, including the six assessment banks and the Writing/Speaking parts: `python scripts/validate_part.py --bank question_bank`
- Writing/Speaking pipeline and reports: `python -m productive.run_all` (build, audit, validate, full test suite).
- Restart the server after pulling changes (`python -m server.dev_server`): an old process keeps serving the old code.

## Listening audio (free, no API key)

Every Listening part (placement and A1..C2) has its recording next to `part.json`: `<audio.file>` (the mp3 name the part already declared) plus `audio-manifest.json` (voices, pace, per-turn start/end, duration, hashes).
Generated with [edge-tts](https://pypi.org/project/edge-tts/) (Microsoft Edge online read-aloud service: free, unofficial, needs internet at generation time only) and ffmpeg.

```
pip install edge-tts                      # ffmpeg + ffprobe must be on PATH
python scripts/generate_listening_audio.py            # all listening parts; finished ones are skipped, failures are reported and can simply be re-run
python scripts/generate_listening_audio.py --only LI001 --force
python scripts/generate_listening_audio.py --dry-run  # voice plan only
```

One voice per speaker (matching the speaker's gender and accent; standard accents only), pace by profile (`config/blueprint.json -> tts.edge`: easy -12%, medium -5%, hard 0%), 0.45 s between turns.
The exam endpoint `GET /api/exam/<exam_id>/audio/<part_id>` streams the mp3 (HTTP Range supported) only for listening parts that belong to that exam.
In the front end the transcript is hidden behind a **Show transcript / Hide transcript** button. That button is a development and review aid: set `LINGO_TRANSCRIPT_TOGGLE=0` (real assessments) and the
transcript is not even sent to the browser when the part has audio. A part without an mp3 falls back to showing the transcript. Machine voices: listen before treating them as final assessment audio.

## Design decisions (all editable in `config/`)

- **Part-level `profile`, item-level `level`.** Parts average easy/medium/hard, but every part contains items from several CEFR levels
  so weak learners can answer something and strong learners are still separated.
- **All items are MCQ.** The original IELTS format is kept in `presentation` so the UI can still render a TFNG or heading-matching style.
- **Evidence is validated verbatim** against the transcript/passage, which catches most hallucinated or unsupported answer keys.
- **Tags come from a fixed taxonomy** so the adaptive-learning step can aggregate weaknesses (skill, grammar rule, vocabulary type, CEFR level).
- **Assembler contract:** pick `parts_per_test` parts per skill from `status in (validated, reviewed, approved)`; for Listening pick one of each
  `part_type` if you want an IELTS-like spread, and choose profiles according to your test blueprint.
- **IDs:** human-readable (`LI001`, `RE001`, `LI001-Q03`) for folders and debugging, plus a stable UUID per part and per item written once by `--stamp` (items use uuid5 of the part UUID, so they never change).
- **Audio later:** after a part is validated, `export_tts_scenario.py` builds the TTS config (preset easy/medium/hard from the profile; the repo's `expert` preset with strong regional accents is never used). Verified against the source repo's own prompt-building code.
- **Status lifecycle:** `draft -> validated (script) -> reviewed -> approved (human)`. Only humans should set reviewed/approved.

## Things to confirm

- Counts: the blueprint uses `items_per_part` Listening = 10 (x4 parts) and Reading = 13 (x3 passages), matching the official IELTS layout.
  Change one line in `config/blueprint.json` if the team decides differently.
- CEFR-to-band mapping is approximate (see `level-calibration.md`).
- Licensing: AI-generated text from these skills is original. If you copy any wording from LuchoBazz/ielts-ai-dataset prompts (CC BY 4.0), keep the attribution.
