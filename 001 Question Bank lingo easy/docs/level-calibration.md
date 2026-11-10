# Level calibration (shared by the Listening and Reading generators)

A placement-test part must be **answerable by every learner and discriminating for strong ones**.
IELTS parts are uniformly hard; ours are not. Difficulty lives at the **item** level, and each part
carries a `profile` that controls the mix.

## 1. The core design rule: plant evidence at every level

Never write the questions first and hope the text supports them. Write the text WITH a deliberate
difficulty ladder, then write one item per planted evidence span.

- **Easy anchors (A1-A2):** a short, simple, explicitly stated fact: a number, name, place, price,
  time, or a plain "who/what/where". Short sentence, high-frequency words, no negation tricks.
  Place at least one early in the text so a weak learner gets a quick win.
- **Middle (B1-B2):** information that requires matching a paraphrase, following a reason/result link,
  or ignoring one plausible distractor.
- **Top (C1-C2):** inference, speaker/writer attitude, implied meaning, nuance between two close options,
  hedged or abstract language, a self-correction or concession the learner must resolve.

A part's *text* sits at `text_cefr` (its overall register); easy anchors are simple sentences
*inside* that text, hard items are dense sentences inside it. Do not lower the whole text to A1 or raise it
to C2 just to hit an item level.

## 2. What each CEFR level means for an ITEM

| CEFR | band (approx.) | The learner must be able to... | Typical item |
|------|----------------|--------------------------------|--------------|
| A1 | 1.0-2.5 | pick out one stated fact in a very short, simple sentence | a number, name, place, "yes/no" fact; options clearly different |
| A2 | 3.0-3.5 | understand simple everyday facts, prices, times, directions | one stated detail; options differ in one obvious word |
| B1 | 4.0-5.0 | follow main points of familiar topics; simple reason/purpose | one detail with a mild distractor; simple paraphrase |
| B2 | 5.5-6.5 | follow longer arguments; match paraphrase; handle distractors | cause/effect, comparison, speaker opinion stated fairly directly |
| C1 | 7.0-8.0 | infer implicit meaning, attitude, organisation | writer/speaker purpose, implication, "what does X suggest" |
| C2 | 8.5-9.0 | fine shades of meaning, abstract/idiomatic language, subtle contrast | two options both partly true; only one fully supported |

The CEFR to IELTS band mapping is an approximation (official IELTS-CEFR alignment starts around band 4.0;
A1/A2 values are our own convention). Always store BOTH `cefr` and `band`; `band` must lie in the range
given in `config/blueprint.json`.

## 3. Profiles (from `config/blueprint.json`)

| Profile | Item mix (target weights) | Required levels | Text register |
|---------|---------------------------|-----------------|---------------|
| foundation | A1 .15, A2 .30, B1 .30, B2 .20, C1 .05 | A1 A2 B1 B2 | A2-B1 (up to B2) |
| intermediate | A2 .10, B1 .25, B2 .35, C1 .25, C2 .05 | A2 B1 B2 C1 | B1-B2 (up to C1) |
| advanced | A2 .05, B1 .15, B2 .30, C1 .35, C2 .15 | A2 B1 B2 C1 C2 | B2-C1 (up to C2) |

Turn weights into integer counts for the part size (e.g. 10 items, intermediate: A2 1, B1 2, B2 4, C1 2, C2 1).
Rules enforced by the validator: required levels present, mean band inside the profile range, no single
CEFR level above 40% of items.

## 4. Writing good multiple-choice items (all levels)

- **Exactly one defensible answer.** Re-read the text with each option; two partly true options are only allowed
  at C1-C2 and only if one is clearly better supported.
- **3 options** is the default (A-C). Use 4 (A-D) only for a minority of B2+ items.
- Distractors: plausible, same grammar and similar length as the key, drawn from the text or from a
  likely misunderstanding. No "all/none of the above", no jokes, no absurd options at B1+.
- **Distractor strength scales with level (B2 and above).** A wrong option must be something a competent but careless
  listener/reader could really choose: a detail that IS in the text but answers a different question, a view the text
  mentions and then rejects, an over-generalisation of a true point, or a partly true statement that goes one step too far.
  Never use extremes ("completely useless", "always", "never", "a waste of land", "no effect at all"), obvious nonsense,
  or an option that the stem already contradicts. If a learner at B1 could eliminate two options without reading/listening,
  the item is NOT C1/C2: re-label it or rewrite the distractors. Do not label an item C1/C2 just because it is an inference
  question; the difficulty must come from the options.
- **Stem must not add logic the text lacks.** Do not join two facts with "because", "so" or "since" in a prompt unless the
  text itself states that link.
- **No overlapping numeric options.** Options such as "an hour" and "two hours" after a text saying "more than an hour" are
  both true. Options must be mutually exclusive.
- **Matching information** (reading): give every item in a group the same number of options (use 4), and choose plausible
  paragraphs as distractors (ones on a related topic), not random ones.
- Key position: spread A/B/C/D evenly. No letter above 50% of the part, never the same letter more than 3 times in a row.
- Stem is a question or a complete lead-in. Avoid negatives ("Which is NOT...") below B2.
- Do not let one item's wording give away another item's answer.
- Keep the stem language at or **below** the item's level; the difficulty should come from the
  text, not from decoding the question. (A1 item: the stem must itself be A1-readable.)
- `explanation`: 1-2 plain sentences saying why the key is right (and, when useful, why the nearest distractor is wrong).

## 5. Metadata that feeds adaptive learning

Every item carries:

- `level` (`cefr` + `band`): how hard the item is.
- `skill_tag` (from `config/taxonomy.json`): what sub-skill it tests (gist, detail, inference, ...).
- `language_focus`: tag the language point the learner needs in order to answer:
  - `{"type":"grammar","rule":"<grammar_rules value>"}` when a grammatical structure is the crux
    (e.g. understanding "I wish you'd told me" needs `conditionals_unreal`).
  - `{"type":"vocabulary","lexical_type":"<lexical_types value>","target":"<word or phrase>"}` when a word/phrase
    is the crux. The `target` is free text: the actual word.
  - `{"type":"none"}` when neither is the crux. Do NOT force a tag onto every item; honest tags only.
- `evidence`: the exact words from the text that justify the answer (validated verbatim).
  Only a "Not Given" answer may have `"evidence": null`.

When a learner fails items, these tags are how the platform finds *why* (a grammar rule, a vocabulary
type, a sub-skill, a CEFR level). Wrong or decorative tags poison that analysis, so tag conservatively.

## 6. Content rules for Arabic-speaking learners

- Neutral, globally accessible topics from `taxonomy.topics`. Avoid alcohol, gambling, dating/romance,
  politics, religion, graphic violence, and anything that needs insider cultural knowledge.
- Do not rely on culture-specific knowledge (sports rules, holidays, brand names) to answer an item.
- Names: a realistic international mix. Spell numbers/dates/prices in a way that is unambiguous.
- Original text only. Never reproduce or closely paraphrase real IELTS/Cambridge material or any copyrighted source.
