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
scripts/validate_part.py  validator, --stamp (derived fields + UUIDs), --bank report (no dependencies)
scripts/export_tts_scenario.py  listening part.json -> tts-config.json for the source repo's generate-tts.py (later step)
config/tts-base-config.json     copy of the source repo's TTS config (voices, delivery presets)
NOTICE.md                 CC BY 4.0 attribution
examples/                 4-item mini parts (LI001, RE001) for testing the pipeline only
```

## Bank layout the skills write to

```
question_bank/
  listening/LI001/part.json   (+ li001_<slug>.mp3 later, from the TTS step)
  listening/LI002/part.json
  reading/RE001/part.json
  reading/RE002/part.json
  writing/   speaking/        (later)
```

## How to use (AntiGravity / Claude Code / any agent that reads SKILL.md)

1. Put the CONTENTS of this folder at your workspace root. Antigravity auto-discovers workspace skills in `.agent/skills/`.
2. Prompt, e.g.: *"Use lingoeasy-reading-generator to generate RE001-RE010 (3 foundation, 4 intermediate, 3 advanced). Validate each one and stamp it."*
3. Check progress anytime: `python scripts/validate_part.py --bank question_bank`
4. Try the pipeline first: `python scripts/validate_part.py examples/question_bank/reading/RE001/part.json --mini`

## Two test types (placement and assessment)

```
question_bank/                      placement bank  (profiles foundation / intermediate / advanced, mixed CEFR levels)
  listening/LI001..LI010   reading/RE001..RE010
question_bank/assessment/<LEVEL>/   assessment banks, one per CEFR level A1 A2 B1 B2 C1 C2
  listening/LI1xx..LI6xx   reading/RE1xx..RE6xx   (10 + 10 parts per level, every item of that level only)
```

- **Placement test** (default): 4 Listening + 3 Reading parts of mixed profiles, indicative level in the result.
- **Assessment test**: pick a level (A1..C2) on the home screen; parts come only from `question_bank/assessment/<LEVEL>/`
  (profile `level_a1` .. `level_c2` in `config/blueprint.json`). The result is a score plus pass/fail (prototype pass mark 60%).
- API: `POST /api/exam/start` with `{"mode": "placement"}` or `{"mode": "assessment", "level": "B1"}`.
- Randomness per attempt: which parts are drawn, the order of parts inside each skill, and the option order of plain
  multiple-choice items (True/False/Not Given, Yes/No/Not Given and matching items keep their natural order).
  The exam screen has a "Test composition" line that lists the part ids of the current attempt.
- Validate everything, including the six assessment banks: `python scripts/validate_part.py --bank question_bank`
- Restart the server after pulling changes (`python -m server.dev_server`): an old process keeps serving the old code.

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
