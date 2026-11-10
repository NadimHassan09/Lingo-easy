---
name: lingoeasy-speaking-generator
description: Generate Lingo Easy SPEAKING parts (one spoken-response task with questions or cue card, plus its evaluation blueprint) for the Placement test or a CEFR level assessment (A1-C2). Use when asked to generate, add, review or regenerate speaking parts (SP001, SP101, ...). IELTS Speaking-inspired, CEFR-calibrated, honest about the text-only MVP (no audio, no pronunciation scoring).
---

# Lingo Easy: Speaking part generator

You generate **one Speaking part per run**. A part = **one coherent speaking task** (a short set of questions, a cue card with follow-ups, a situation to respond to, or a discussion)
plus the metadata a future evaluator needs. It is open-ended: there is no answer key, and many responses are valid.

```
question_bank/placement_test/speaking/<ID>/part.json            (placement: tasks spread over A1-C2)
question_bank/assessment_test/<LEVEL>/speaking/<ID>/part.json   (assessment: every task targets <LEVEL>)
```

IDs: placement `SP001`-`SP010`; assessment `SP1xx` (A1), `SP2xx` (A2), `SP3xx` (B1), `SP4xx` (B2), `SP5xx` (C1), `SP6xx` (C2).

Read first, every run:
1. `config/taxonomy.json` (topics, grammar rules, `skill_tags.speaking`, `presentations.speaking`) and `productive/config/productive_taxonomy.json` (per-level duration, preparation, typed-word limits, formats with criterion weights, cognitive processes, diagnostics, placement design).
2. `config/blueprint.json` (`cefr_to_band`, `productive.speaking.parts_per_test`), `docs/level-calibration.md`.
3. `references/speaking-level-matrix.md` in this skill folder.
4. Existing speaking parts of the same bank (titles, topics, formats).

## Reference and architecture

The Speaking generator is **not** part of LuchoBazz/ielts-ai-dataset (that repository has Writing, Reading and Listening resources only; license CC BY 4.0). This skill therefore adapts:
- the **structure** of the repository's generator skill (`skills/ielts-listening-generator/SKILL.md`: purpose, core principle, parameters, authenticity rules, output format, workflow), also used by Lingo Easy's Reading/Listening skills;
- the **IELTS Speaking design ideas**: Part 1 (familiar topics, short answers), Part 2 (individual long turn with a cue card and preparation time), Part 3 (abstract discussion that extends the Part 2 topic). These are *inspirations*; below B1 we use simpler formats, and C-level tasks raise cognitive demand, not length.
Everything is original wording. Keep `NOTICE.md` with the kit.

## CURRENT MVP LIMITATION (must be reflected in every part)

The application does **not** record audio and has **no speech-to-text**. The learner types a response (or types into a "transcript" box). Therefore:
- Parts must tell the learner: type your answer the way you would say it; pronunciation is not assessed in this version.
- The evaluation blueprint must mark **S_PRON (pronunciation) as not assessable** (`not_assessed_by_design`, never a scored criterion) and **S_FC (fluency and coherence) as `partial`**:
  only organisation and coherence can be judged from text; speech rate, pauses, hesitation, self-correction and intonation cannot.
- Never write guidance that implies a typed answer shows pronunciation or oral fluency. Never fabricate audio fields. Optional future fields exist only in the schema (`audio_extension`: audio reference, duration, transcript, STT provider/confidence, pronunciation/fluency evaluation) and stay absent until real audio exists.
- Distinguish in the blueprint: **evaluable from a transcript** (vocabulary, grammar, relevance, development, coherence), **requires audio** (pronunciation, fluency, intonation), **future audio version** (all of the latter plus STT-confidence handling).

## Hard rules (the validator enforces most)

- One task per part; original wording; no copied exam questions; no model answers (`expected_response.examples` = illustrative outline, labelled "not an answer key").
- **Allowed formats** (`productive_taxonomy.json -> speaking.formats`): `familiar_topics`, `situational_response`, `long_turn`, `long_turn_discussion`, `discussion`.
  - Long turns: a cue card with 3-5 points, preparation time (0-90 s by level), speaking time. Discussion tasks need follow-up questions that **invite elaboration** (from B1: not yes/no only; use why / how / to what extent / compare ...).
  - A1: 3-4 very short questions, or a very simple role-play, or a cue of 4 simple questions; no preparation. A2: connected answers with a reason; at most 30 s preparation.
  - B1/B2: extended answers, comparison, opinion, speculation. C1/C2: abstract topics, qualified stance, hypotheticals, tactful interaction; harder because of *reasoning and precision demanded*, not more questions.
- **Level-pure assessment, spread placement** (placement: A1 x1, A2 x2, B1 x2, B2 x2, C1 x2, C2 x1; none duplicating an assessment task).
- **Typed length must be consistent with the suggested speaking time** (config pace per level: A1 70, A2 85, B1 100, B2 120, C1 135, C2 150 spoken words per minute; typed expectation about 30-110 percent of that). Duration and preparation must be inside the level range.
- Allowed values only (topics, grammar ids, sub-skills, cognitive processes, diagnostics). Missing value? Stop and report.
- Culturally safe for Arabic-speaking learners (see the Writing skill's list); no questions that need private disclosure (religion, politics, income); personal questions stay everyday-level.
- Do not fill `uuid`, `derived`, `provenance`, `qa` by hand.
- Learner-facing text never contains rubric, level, band, diagnostics or outline.

## Parameters
bank (`placement` or `A1`..`C2`), count (default 10), topic (least used), format (least used; at least 3 different formats in a bank of 10; none more than 5 times).

## Workflow

### Step 0: Context
List existing speaking parts in the target bank; pick the next free ID, an under-used topic (max twice per bank) and format.

### Step 1: Plan (show briefly)
id / bank / target CEFR / band reference; format; scenario; main question; cue-card points or follow-up questions; preparation and speaking seconds; typed words (min / suggested min / suggested max);
grammar structures invited (>= 1 at target level, none above target + 1); cognitive operations; sub-skills; learning objective(s).

### Step 2: Write the spec
Fields (glossary at the top of `productive/specs/speaking_a.py`):
`k, lv, fmt, topic, title, scen, prompt, main, cue, follow, prep, dur, w=[min, suggested_min, suggested_max], vocab, gram, sub, sub2, cog, obj, outline, abs`.
- `prompt` = the learner instruction (what to do, how long, whether there is preparation). `main` = the question or situation opener. `cue` only for long turns. `follow` = follow-ups.
- Situational tasks: the examiner/interlocutor lines are the questions; the learner answers in role. Do not put the learner's side of the dialogue in the task.
- Do not put answers in the prompt. The learner must produce the content.
- `abs` (0-3) must fit the level range.

### Step 3: Evaluation blueprint (generated; check it)
Criteria: S_REL relevance and task fulfilment, S_LR lexical resource, S_GRA grammatical range and accuracy, S_DEV development of ideas, S_FC fluency and coherence (**partial** in text),
S_PRON pronunciation (**unavailable**, weight 0). The blueprint carries per-criterion descriptors by level, expected evidence, common error patterns (L1-transfer hypotheses at A1-B2),
limitations, `not_penalised` (e.g. spelling and punctuation in the typed text; short answers at A1), `text_mvp_limitations` and the evaluator output contract. Check weights sum to 1 over the scored criteria.

### Step 4: Diagnostics
Same policy as Writing: an observed error is not a learner weakness. The category `D_TEXT_ONLY_LIMIT` is always included for speaking parts.

### Step 5: Build, validate, stamp
```bash
python -m productive.generate --spec-file path/to/spec.json --skill speaking --bank C1 [--id SP511]
python -m productive.build
python scripts/validate_part.py --bank question_bank
python -m productive.validate
```
Fix every ERROR; read every WARN. Status stays `validated` at most.

### Step 6: Report
Part ID, bank, target CEFR and band reference, format, topic, main question, follow-ups or cue points, durations, typed word range, criteria and weights, heuristic CEFR and confidence,
validator warnings, and what a human should check (naturalness when read aloud, question order, cultural fit, whether follow-ups really invite elaboration).

## Quality self-check
- Read the questions aloud: would an examiner really say this? Is each question answerable from everyday experience at that level?
- Do the follow-ups ask *why / how / what if* rather than yes/no from B1? Does a C-level task demand reasoning, qualification or hypotheticals rather than only speaking longer?
- Is the typed length realistic for the stated speaking time? Is pronunciation claimed anywhere? (It must not be.)
- Is the topic/format new for this bank, and is the learning objective different from the other nine tasks?
- Placement: do the ten tasks progress A1 to C2? Say what each shows and where evidence is thin.

## Future integration points (do not implement here)
Microphone capture -> audio asset -> STT -> transcript stored in `audio_extension` and in the attempt record (`transcript_source: "stt"` instead of `"manual_entry"`) -> audio-aware evaluation of S_PRON and the fluency part of S_FC.

## Never
Never fabricate audio, STT output, pronunciation scores, learner responses or human approval. CEFR labels are the author's intent plus a heuristic check, not calibrated values.
