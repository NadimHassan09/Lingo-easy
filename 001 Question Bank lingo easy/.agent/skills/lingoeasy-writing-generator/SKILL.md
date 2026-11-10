---
name: lingoeasy-writing-generator
description: Generate Lingo Easy WRITING parts (one open-ended writing task plus its evaluation blueprint) for the Placement test or for a CEFR level assessment (A1-C2). Use when asked to generate, add, review or regenerate writing parts (WR001, WR101, ...) in the question bank. IELTS-inspired, CEFR-calibrated, evaluation-ready for a future LLM assessor.
---

# Lingo Easy: Writing part generator

You generate **one Writing part per run** (or a batch, one at a time). A part = **one coherent writing task** + the metadata a future evaluator needs
(task definition, expected response, evaluation blueprint, diagnostics, difficulty). It is *not* multiple choice and it has *no answer key*:
many different responses are valid. Parts are saved under the unified bank:

```
question_bank/placement_test/writing/<ID>/part.json            (placement: tasks spread over A1-C2)
question_bank/assessment_test/<LEVEL>/writing/<ID>/part.json   (assessment: every task targets <LEVEL>)
```

IDs: placement `WR001`-`WR010`; assessment `WR1xx` (A1), `WR2xx` (A2), `WR3xx` (B1), `WR4xx` (B2), `WR5xx` (C1), `WR6xx` (C2).

Read these first, every run (never hard-code values that live there):
1. `config/taxonomy.json`: topics, grammar rules, `skill_tags.writing`, `presentations.writing` (shared vocabularies, same as Reading/Listening).
2. `productive/config/productive_taxonomy.json`: per-level word-count / time / abstractness limits, task categories with criterion weights, cognitive processes (with levels), diagnostic categories, placement design.
3. `config/blueprint.json` (`cefr_to_band`, `productive.writing.parts_per_test`) and `docs/level-calibration.md` (what each CEFR level means).
4. `references/writing-level-matrix.md` in this skill folder: task types, length and demand per level.
5. A few existing parts of the same level (`question_bank/**/writing/*/part.json`) to avoid duplicates and copy the conventions.

## Reference and attribution

Adapted from the Writing generation approach of **LuchoBazz/ielts-ai-dataset** (CC BY 4.0, https://github.com/LuchoBazz/ielts-ai-dataset; `prompts/*/ielts-writing-generator.md`)
and the supplied `ielts-writing-generator.md`. Ideas kept: one test = defined tasks with a title, suggested time, prompt, minimum words; a **target band** that
governs topic abstraction, prompt vocabulary and cognitive demand; a described **stimulus** for data-based tasks (we store it as `task.stimulus` text, no image is generated);
tasks drawn from IELTS-style types. Ideas changed: levels are CEFR A1-C2 (band = approximate equivalent, `config/blueprint.json cefr_to_band`); IELTS Task 1 / Task 2 are
*inspirations*, not formats forced on every level; output is the Lingo Easy part schema, not the repo's test JSON. Wording is original. Keep `NOTICE.md` with the kit.

## Hard rules (the validator enforces most of these)

- **One task per part.** Do not split one coherent task into several parts and do not bundle unrelated tasks.
- **Original tasks only.** Never copy or closely paraphrase official IELTS or published exam questions.
- **No answer key.** Never store a "model answer". `expected_response.examples` holds an *illustrative outline*, labelled "not an answer key".
- **Level-pure assessment, spread placement.** Assessment parts: `target_cefr` = the assessment level (adjacent-level structures allowed only when justified; they are reported in `difficulty.adjacent_level_demands`).
  Placement parts: the 10 placement tasks follow `placement_design.level_counts` in `productive_taxonomy.json` (A1 x1, A2 x2, B1 x2, B2 x2, C1 x2, C2 x1) and differ from every assessment task.
- **Raise real demand, not length.** Going up a level must change the linguistic and cognitive demand (grammar invited, cognitive operation, abstractness, register), not just the topic or word count.
- **The prompt must be readable at the target level.** A1/A2 prompts: short sentences, high-frequency words (limits in `productive_taxonomy.json -> writing.levels.<L>`).
- **Allowed values only.** Topics, grammar ids, sub-skills, cognitive processes, task categories and diagnostic ids come from the config files. If one is missing, stop and say so so it can be added there first.
- **Culturally safe for Arabic-speaking learners.** No alcohol, dating, gambling, pork, religion/party politics, or topics that need insider knowledge of one culture. Tasks must not require outside facts the learner cannot be expected to know.
- **Do not fill** `uuid`, `derived`, `provenance`, `qa` by hand: the generator does it.
- Learner-facing text never contains the rubric, level label, band, diagnostics or the outline.

## Parameters (ask or default)

| Parameter | Values | Default |
|---|---|---|
| bank | `placement` or `A1`..`C2` | required |
| count | number of parts | 10 per bank |
| topic | from `taxonomy.json` | least-used topic in that bank |
| task category | one of `productive_taxonomy.json -> writing.categories` | least-used category in that bank |

## Workflow

### Step 0: Context
List existing writing parts in the target bank (titles, topics, categories, levels). Pick the next free ID. Choose an under-used topic and task category (no topic more than twice per bank; no category more than 4 times in a bank of 10).

### Step 1: Plan before writing (show this table briefly)

| field | value |
|---|---|
| id / bank / target CEFR / band reference | |
| task category / purpose / audience / register | |
| topic and scenario (1-2 sentences, concrete, answerable from personal knowledge) | |
| required points (count per level: A1 3-6, A2 3-5, B1 2-5, B2 2-5, C1 2-5, C2 1-5) | |
| grammar structures invited (>= 1 at target level; none above target + 1) | |
| cognitive operations (>= 1 at target level or one below) | |
| primary and secondary sub-skills, learning objective(s) (start with a measurable verb: write, describe, explain, compare, argue ...) | |

### Step 2: Write the task spec
Fill the **spec** fields (glossary in `productive/specs/__init__.py`):
`k, lv, cat, topic, title, scen, prompt, pts, aud, reg, w=[min, suggested_min, suggested_max, max], mins, vocab, gram, struct, sub, sub2, cog, obj, outline, opt, abs, stim?`.

Writing the prompt and instructions:
1. State the situation, the communicative purpose and the audience. Give required points as a short list. Say the length range and the time.
2. Give enough guidance to be answerable, not so much that the answer becomes predictable (do not hand over the sentences or the ideas).
3. Use IELTS-style wording only where it fits the level: e.g. "Discuss both views and give your own opinion" (B2+), "To what extent do you agree" (B2+), "Write a letter/email to ..." (A2+). Do not use academic discourse prompts below B1.
4. Data tasks (B2+ reports): put the data in `stim` (a small table or list in plain text, 25+ tokens), say "do not invent additional data" in `opt`. No images are produced in this version.
5. `outline` = 3-6 neutral bullet points of one possible structure. It must not contain finished sentences a learner could copy at A1/A2.
6. `abs` (abstractness 0-3) must fit the level range in the config.

Length, time and demand per level: see `references/writing-level-matrix.md`. The word count must be realistic for the level; time must give 3-14 words per minute overall.

### Step 3: Evaluation blueprint (generated, but you must check it)
The generator builds the blueprint from the category and level: weighted criteria (task fulfilment, coherence and cohesion, lexical resource, grammatical range and accuracy,
register and appropriateness where the task defines an audience, organisation and development for essay-type tasks from B1/B2), each with successful/weak performance, expected evidence,
common error patterns (including Arabic-L1 transfer hypotheses at A1-B2, marked as hypotheses), related sub-skills and limitations; plus `required_demonstrations`,
`optional_demonstrations`, **`not_penalised`** (what must not lower the score because the task does not require it), `not_assessed_by_design`, the per-criterion CEFR-estimate scale and the
evaluator output contract. Check that:
- A1/A2 tasks are **not** judged with essay-organisation or argument criteria. Advanced tasks are **not** judged mostly on basic accuracy.
- Register-sensitive tasks (formal email, report, proposal, register transformation) include the register criterion.
- Criterion weights sum to 1.

### Step 4: Diagnostics
`diagnostics.targets` are the categories (from `productive_taxonomy.json -> diagnostics.categories`) an evaluator can look for in this task. An *observed error* is not a *learner weakness*:
a weakness may be inferred only after repeated evidence (policy stored in each part). Never claim a permanent weakness from one instance.

### Step 5: Build, validate, stamp
```bash
# one new part from a spec JSON (writes the part, validates it, stamps status):
python -m productive.generate --spec-file path/to/spec.json --skill writing --bank B2 [--id WR411]
# whole bank + reports (the 70+70 authored specs):
python -m productive.build
# validate everything including the other skills:
python scripts/validate_part.py --bank question_bank
python -m productive.validate
```
Fix every ERROR (never loosen a rule or a config limit to make a part pass). WARN lines (`cefr_estimate_differs_from_target`, `prompt_sentences_too_long`, ...) must be read and either fixed or explained in the part's notes.
Status stays `validated` at most; only humans set `reviewed` or `approved`.

### Step 6: Report
Reply with: part ID, bank, target CEFR and band reference, category, topic, required points, word range and time, sub-skills, criteria and weights, heuristic CEFR estimate and confidence, validator warnings,
and anything a human reviewer should check (cultural fit, ambiguity, a prompt that may be too guiding).

## Quality self-check (before building)
- Could an A2 learner understand the prompt on first reading? Could a C1 learner score high only by writing *more*? Then the demand is wrong.
- Does the task allow several equally valid responses? Is any required content knowledge outside the learner's likely experience?
- Is every required point observable in the response (so an evaluator can check it)? Are the criteria the ones the task actually exercises?
- Is the topic/category new for this bank? Is the learning objective different from the other nine tasks (not just a different topic)?
- Does the scenario avoid sensitive subjects and culture-bound assumptions?
- Placement only: do the ten tasks together show a clear progression A1 to C2? State what each task contributes. Remember ten tasks are a product constraint, not proof of reliability; say where evidence is thin (one A1, one C2).

## Never
Never fabricate evaluation results, learner responses or human approval. Never mark CEFR labels as calibrated: they are the author's intent plus a heuristic check.
