---
name: lingoeasy-reading-generator
description: Generate Lingo Easy placement-test READING parts for the question bank. One part = one passage plus N multiple-choice items with mixed CEFR levels, verbatim evidence and adaptive-learning metadata. Use when asked to generate, add, or regenerate reading parts (RE001, RE002, ...) for the question bank.
---

# Lingo Easy: Reading part generator

You generate **one Reading part per run** (or a batch, one part at a time) and save it as
`question_bank/placement_test/reading/<ID>/part.json`. A part is a placement-test unit, not an official IELTS paper. (Assessment-level parts go to `question_bank/assessment_test/<LEVEL>/reading/` since the four-skill layout change; that is the only edit made to this skill.)

Read these first, every run:
1. `config/blueprint.json`: item count, profiles, CEFR-band ranges, part types. **Never hard-code counts; read them.**
2. `config/taxonomy.json`: the only allowed values for topics, skill tags, grammar rules, vocabulary types.
3. `docs/level-calibration.md`: how to build a part that every learner can enter and strong learners cannot max out trivially.
4. `schemas/part.schema.json`: the exact JSON shape.

## Hard rules (the validator enforces these)

- **All items are multiple choice**, even when the original IELTS format would be completion, matching or drag-and-drop.
  Record the original format in the group's `presentation` field (`multiple_choice`, `true_false_not_given`, `yes_no_not_given`,
  `sentence_completion`, `summary_completion`, `matching_headings`, `matching_information`), but the learner always *chooses* an option.
  - `true_false_not_given`: options must be exactly `True / False / Not Given`. `yes_no_not_given`: exactly `Yes / No / Not Given`.
  - `sentence_completion` / `summary_completion`: prompt contains the sentence with a gap shown as `_____`; options are the candidate completions.
  - `matching_headings`: one item per paragraph; options are candidate headings (A-C, sometimes D).
  - `matching_information`: prompt is a statement; options are paragraph labels (use the real labels as option text, for example "Paragraph B").
  - Never ask the learner to type anything.
- Item count per part = `items_per_part` from the blueprint, split across 1-4 `question_groups`, numbered continuously from 1. Choose the number of groups at random per part (1, 2, 3 or 4, favouring 2-3), split the items unevenly, and never exceed 4 groups.
  Mix presentations within a part (for example one MCQ group + one TFNG group) to keep it varied, but keep each group homogeneous.
- **Each item** has `level {cefr, band}`, `skill_tag`, `language_focus`, `evidence`, `explanation`. CEFR and band are both mandatory.
- The **part** has `profile` and `text_cefr`; the item-level mix follows the profile.
- `evidence {paragraph, quote}`: the quote must be copied **verbatim** from that paragraph (3+ words; punctuation ignored).
  Only an item whose correct answer is `Not Given` may use `"evidence": null`.
- Passage = labelled paragraphs `A, B, C, ...` in order (no gaps). Plain text, no markdown.
- Length is enforced: count your words. Language models tend to under-deliver length (the source repo's own reading samples came out 20-40% below the requested 600-800 words), so if the passage is under the range for the profile, develop it further with real content, not repetition.
- Do not fill `derived` or any `uuid`. The stamp step does that.
- Do not invent tag values; if one is truly missing, stop and say so so the team can add it to `taxonomy.json`.

## Workflow

### Step 0: Context and de-duplication
- List existing `question_bank/placement_test/reading/*/part.json` (titles, topics, part types). Pick the next free ID (`RE001`, `RE002`, ...).
  If the user gave a batch plan, follow `bank_targets` in the blueprint and choose the profile furthest below target.
- Pick an under-represented **topic** from the taxonomy and a **part_type**:
  - `descriptive`: explains how something works, what something is, or what happened.
  - `discursive`: weighs several viewpoints or considerations.
  - `argumentative`: the writer defends a position (good for `writer_claim` / `yes_no_not_given`).

### Step 1: Plan before writing (show this plan briefly in your reply)
Plan table: `profile, text_cefr, topic, part_type, group layout` and one row per item:

| # | cefr | band | skill_tag | presentation | language_focus | planted evidence idea (paragraph) |
|---|------|------|-----------|--------------|----------------|-----------------------------------|

Turn the profile weights from `level-calibration.md` into integer counts for `items_per_part`, satisfy `required_levels`,
and spread evidence over all paragraphs. Reading items need not follow text order strictly, but groups should roughly follow it.

### Step 2: Write the passage with the difficulty ladder built in
- Length: `text_words.reading` range for the profile. Original text only: never copy or closely paraphrase published articles or exams.
- The text sits at `text_cefr` overall. Deliberately include:
  - **Easy anchors** (A1-A2): short, explicit sentences with a plain fact, ideally in the first or second paragraph.
  - **Mid-level spans** (B1-B2): causes/effects, comparisons, information that is re-worded in the options.
  - **Hard spans** (C1-C2): hedged claims, concession, implied meaning, abstract noun phrases, a writer's stance.
- Make the text read like a real article: a clear title, an opening that sets the topic, coherent development, a closing paragraph with a conclusion or outlook.
- Neutral, factual-sounding content. If real facts/figures are used, they must be plausible and not misleading; prefer general or clearly illustrative detail over specific statistics you cannot verify.
- Plant one evidence span per planned item. For `Not Given` items, write the passage so the statement is *about* the topic but genuinely unaddressed.

### Step 3: Write the items
Apply the item rules in `docs/level-calibration.md` section 4. For reading specifically:
- `skill_tag` guidance: A1-A2 -> `specific_detail`; B1 -> `specific_detail`, `paraphrase_matching`, `vocabulary_in_context`,
  `reference_resolution`; B2 -> `text_organisation`, `fact_check`, `heading_matching`, `summary_gap`; C1-C2 -> `inference`, `writer_claim`, `main_idea` (abstract).
- Options re-word the text; do not copy the evidence sentence word for word into the key, or the item becomes trivial word-matching (acceptable only at A1-A2).
- TFNG/YNNG: `True`/`Yes` = text agrees, `False`/`No` = text contradicts, `Not Given` = not addressed. Keep the three answers well balanced across a group.
- `language_focus` only when truthful (see `docs/level-calibration.md` section 5). `vocabulary_in_context` items should name the exact `target` word.

### Step 4: Assemble `part.json`
Follow `schemas/part.schema.json`. Required top-level keys: `schema_version` (`"1.0"`), `id`, `skill: "reading"`, `part_type`, `title`, `topic`,
`profile`, `text_cefr`, `passage {title, paragraphs[]}`, `question_groups[]`, `assets: []`, `meta`.
- `meta`: `{"status":"draft","source":"ai_generated","generator":"lingoeasy-reading-generator@1.0","model":"<your model name>"}`.
- Save to `question_bank/placement_test/reading/<ID>/part.json` (folder name = part id).

### Step 5: Validate, fix, stamp
```bash
python scripts/validate_part.py question_bank/placement_test/reading/<ID>/part.json
```
Fix every `ERROR` and re-run until clean (never loosen rules or edit the config to make a part pass). Then:
```bash
python scripts/validate_part.py question_bank/placement_test/reading/<ID>/part.json --stamp
```
After a batch: `python scripts/validate_part.py --bank question_bank` and check the coverage report.

### Step 6: Report
Reply with: part ID, title, profile, part type, topic, item level counts, mean band, answer distribution, and anything a human reviewer should look at
(for example a C2 item, or a `Not Given` item that could be argued).

## Quality self-check before validating
- Can an A2 learner answer the easy anchors by reading a single simple sentence? Do the C1 items truly need inference rather than word-matching?
- Exactly one defensible answer per item? Any item answerable without reading the passage (general knowledge)? Any item whose answer is given away by another item?
- Is the passage free of culture-bound assumptions and sensitive topics?
- Distractors (B2+): is every wrong option plausible and drawn from the passage or a likely misreading? Remove extremes ("always", "completely", "never"), absurd options and options the stem contradicts. Could a B1 learner eliminate two options without reading? Then the item is not C1/C2.
- Does any prompt join two facts with "because/so/since" that the passage does not join? Are numeric or time options mutually exclusive?
- Matching-information groups: same number of options for every item (4), plausible paragraph distractors.
