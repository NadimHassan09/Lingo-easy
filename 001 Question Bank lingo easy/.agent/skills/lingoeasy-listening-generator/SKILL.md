---
name: lingoeasy-listening-generator
description: Generate Lingo Easy placement-test LISTENING parts for the question bank. One part = one text-only audio script (to be converted to mp3 later) plus N multiple-choice items with mixed CEFR levels, evidence and metadata. Use when asked to generate, add, or regenerate listening parts (LI001, LI002, ...) for the question bank.
---

# Lingo Easy: Listening part generator

You generate **one Listening part per run** (or a batch, one part at a time) and save it as
`question_bank/placement_test/listening/<ID>/part.json`. A part is a placement-test unit, not an official IELTS paper. (Assessment-level parts go to `question_bank/assessment_test/<LEVEL>/listening/` since the four-skill layout change; that is the only edit made to this skill.)

Read these first, every run:
1. `config/blueprint.json`: item count, profiles, CEFR-band ranges, part types. **Never hard-code counts; read them.**
2. `config/taxonomy.json`: the only allowed values for topics, skill tags, grammar rules, vocabulary types, accents.
3. `docs/level-calibration.md`: how to build a part that every learner can enter and strong learners cannot max out trivially.
4. `schemas/part.schema.json`: the exact JSON shape.
5. `.agent/skills/lingoeasy-listening-generator/references/part-type-playbook.md`: how each part type sounds, distractor policy by profile, how to speak data. **Read the section for your part_type before drafting.**

## Hard rules (the validator enforces these)

- **Do NOT generate audio.** Write only the transcript. A later step turns it into an mp3; `audio.file` is just the planned file name.
- **All items are multiple choice**, even when the original IELTS format would be completion/matching/map. Keep the original
  format in the group's `presentation` field, but the learner always *chooses* an option (A-C, sometimes A-D). Never ask the learner to type.
- Item count per part = `items_per_part` from the blueprint. They are split across 1-4 `question_groups` (each group: a short shared
  instruction; items numbered continuously from 1). Choose the number of groups at random per part (1, 2, 3 or 4, favouring 2-3) and split the items unevenly; never give every part the same layout. Never exceed 4 groups.
- **Each item** has: `level {cefr, band}`, `skill_tag`, `language_focus`, `evidence`, `explanation`. Both CEFR and band are mandatory.
- The **part** has `profile` (foundation / intermediate / advanced) and `text_cefr`. The mix of item levels follows the profile.
- **Items follow the order of the audio.** Item N's evidence must occur at or after item N-1's evidence in the transcript.
- `evidence.quote` must be copied **verbatim** from one transcript turn (3+ words). Punctuation is ignored, wording is not.
- Transcript is plain spoken text only: no stage directions, no `[pause]`, no markup, no `*`. It goes straight to TTS.
- Every speaker gets a short `role` (for example `hotel receptionist`, `tutor`) for the later TTS step.
- Length is enforced: count your words. Language models tend to under-deliver length (the source repo's own samples came out 20-40% below their targets), so if the transcript is under the range for the profile, extend it with more natural content, not filler.
- Do not fill `derived` or any `uuid`. The stamp step does that.
- Do not invent new tag values. If you truly need one, stop and say so; the team adds it to `taxonomy.json` first.

## Workflow

### Step 0: Context and de-duplication
- List existing `question_bank/placement_test/listening/*/part.json` (titles, topics, part types). Pick the next free ID
  (`LI001`, `LI002`, ...). If the user gave a batch plan (for example "30 foundation, 40 intermediate, 30 advanced"),
  follow `bank_targets` in the blueprint and choose the profile that is furthest below target.
- Choose a **topic** from the taxonomy that is under-represented, and a **part_type**. Rotate through the four types
  so the bank has plenty of each:
  - `social_conversation`: 2 speakers, everyday service/arrangement dialogue (booking, enquiry, plans, problem solving).
  - `social_monologue`: 1 speaker, everyday talk or announcement (tour intro, event info, local service).
  - `academic_discussion`: 2-4 speakers, study context (students/tutor, project planning, feedback, choosing a topic).
  - `academic_lecture`: 1 speaker, a short educational talk with clear organisation.
  Obey the speaker-count range for the part_type in the blueprint.

### Step 1: Plan before writing (show this plan briefly in your reply)
Produce a plan table: `profile, text_cefr, topic, part_type` and one row per item:

| # | cefr | band | skill_tag | language_focus | planted evidence idea |
|---|------|------|-----------|----------------|-----------------------|

Convert the profile weights in `level-calibration.md` into integer counts for `items_per_part`, satisfy the profile's
`required_levels`, and order the rows by where the evidence will occur in the audio (increasing). Levels do NOT have to rise in
order; mix them so the part does not feel like a staircase (but put an easy anchor early).

### Step 2: Write the transcript with the difficulty ladder built in
- Length: `text_words.listening` range for the profile (a 140-150 wpm speaking rate is the target; about 2.5-5 minutes).
- Write for the **ear**: contractions, short sentences, natural signposting ("Right, first...", "Another thing is..."),
  occasional self-correction or change of mind where a C-level item needs it, numbers/dates/times as people really say them.
  Light, natural fillers are fine ("well", "you know", "actually") but never in a way that harms clarity at low profiles.
- Plant one evidence span per row of the plan. Keep easy anchors simple and explicit; make hard spans genuinely need inference,
  attitude, or resolving a distractor (for example a corrected number, a rejected option).
- Keep distractor information **in the audio** for B2+ items (a rejected price, an alternative date) so options are plausible.
- Spell out what must be said aloud: write "ninety pounds" or "9 0 pounds" per TTS-friendliness choice, but be consistent.
  Prefer words for numbers, times and prices.
- Speakers: assign `S1`, `S2`, ... with a realistic name, `role`, `gender`, and `accent` from the taxonomy (clear standard accents only). Mix accents and genders across the bank.

### Step 3: Write the items
Apply the item rules in `docs/level-calibration.md` section 4. For listening specifically:
- The stem is heard in the instruction only, so make it short and self-contained.
- `skill_tag` values to prefer by level: A1-A2 -> `specific_detail`, `numbers_dates_times`; B1 -> `specific_detail`, `purpose`,
  `paraphrase_recognition`, `sequence`; B2 -> `distractor_resolution`, `organisation_signposting`, `speaker_opinion`;
  C1-C2 -> `inference`, `speaker_attitude`, `gist` (for abstract gist).
- Include a `language_focus` ONLY when it is true (see `docs/level-calibration.md` section 5).

### Step 4: Assemble `part.json`
Follow `schemas/part.schema.json`. Required top-level keys: `schema_version` (`"1.0"`), `id`, `skill: "listening"`, `part_type`,
`title`, `topic`, `profile`, `text_cefr`, `audio {file, speakers[{id,name,role,gender,accent}], transcript[]}`, `question_groups[]`, `assets: []`, `meta`.
- `audio.file`: `<id lowercase>_<short_title_slug>.mp3`, for example `li014_flat_viewing_enquiry.mp3`.
- `meta`: `{"status":"draft","source":"ai_generated","generator":"lingoeasy-listening-generator@1.0","model":"<your model name>"}`.
- Save to `question_bank/placement_test/listening/<ID>/part.json` (folder name = part id).

### Step 5: Validate, fix, stamp
```bash
python scripts/validate_part.py question_bank/placement_test/listening/<ID>/part.json
```
Fix every `ERROR` and re-run until clean (do not loosen the rules or edit the config to make a part pass). When clean:
```bash
python scripts/validate_part.py question_bank/placement_test/listening/<ID>/part.json --stamp
```
After a batch, run `python scripts/validate_part.py --bank question_bank` and read the coverage report for shortages.

### Step 6: Audio later (do not do it now)
Audio is a separate, later step. When the team is ready: `python scripts/export_tts_scenario.py question_bank/placement_test/listening/<ID>/part.json`
writes a `tts-config.json` that the source repo's `generate-tts.py` can consume. Do not run it or call any TTS API unless asked.
Audio (since the audio step was added): after validating and stamping a part, run `python scripts/generate_listening_audio.py --only <ID>` to create its mp3 + `audio-manifest.json` in the part folder (free edge-tts voices, no API key). The part's `audio.file` name is the reference; do not edit part.json for audio.

### Step 7: Report
Reply with: part ID, title, profile, part type, topic, item level counts, mean band (from the validator), anything you were unsure about
(for example a C2 item that deserves human review). Do not paste the whole JSON unless asked.

## Quality self-check before validating
- Could an A2 learner genuinely answer the easy anchors from what is said? Could a C1 learner NOT answer the hard items without understanding implication?
- Would a native speaker agree there is exactly one best answer per item?
- Is any answer revealed by a different item's stem or by option wording?
- Is the audio topic neutral and free of culture-bound knowledge?

## Distractor quality check (before validating)
- For B2+ items every wrong option must be plausible: something said in the audio but answering a different question, a rejected or corrected option, or an over-generalisation. No extremes ("completely useless", "always", "never", "a waste of land") and no nonsense options.
- If a B1 listener could discard two options without hearing the audio, the item is not C1/C2: re-label it or rewrite the options.
- Do not join two facts with "because/so/since" in a prompt unless the speaker does. Options must be mutually exclusive (not "an hour" next to "two hours").
- Write quoted speech without needing quotation marks: it will be read by TTS (say "If you ask people whether they agree that apps are useful..." rather than a bare quoted question).
