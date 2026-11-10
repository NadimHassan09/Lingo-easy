# Part-type playbook (listening)

Conventions per `part_type`, adapted for a **multiple-choice placement test with mixed CEFR levels**.
The structure of this playbook (four part types, what each sounds like, how distractors work, how data is spoken)
is adapted from the `ielts-listening-generator` skill in LuchoBazz/ielts-ai-dataset (CC BY 4.0). Wording and the
profile-based rules below are new. See `NOTICE.md` at the kit root.

## Rules that apply to every part type

- **Clear, standard accents only** (`british`, `american`, `australian`, `new_zealand`). Difficulty must come from register,
  vocabulary, structure and distractors, never from mumbling, slang-heavy speech, or speed.
- **Distractor policy depends on the item, not the whole part.** A self-correction or rejected option may sit next to
  B2+ evidence. Do NOT put a distractor on an A1-A2 anchor: those items must be answerable from one clean, explicit statement.
- **Distractor density by profile:** foundation = light (one mild correction at most, next to a B1/B2 item);
  intermediate = medium (2-3 corrections/rejections); advanced = medium-heavy, but still intelligible on first hearing.
- **Spoken data:** say numbers, prices, dates, times, codes the way people say them. Write them in words in the transcript
  (`ninety pounds`, `the fourteenth of March`, `half past seven`). Spell a surname letter by letter only if an item needs it.
- **MCQ conversion of "form data":** IELTS often tests spelling/numbers by completion. Here, turn them into choices with
  *near-miss* options (`15 / 50 / 14`, `Harrison / Harris / Harrington`). The near-misses should be things a careless listener
  might really hear.
- **Answers in order:** evidence for item N occurs after item N-1.
- **Register scales with profile.** An `academic_lecture` at `foundation` is a short, simple talk (A2-B1 register,
  short sentences, explicit signposting); at `advanced` it is dense (nominalisation, abstract nouns, hedging).

## social_conversation (2 speakers)

- Setting: booking, enquiry, registration, arranging a service, solving a small problem.
- One speaker drives (asks), the other gives details. Read-backs are natural ("So that's Friday at six, right?").
- Typical intake order: purpose, people/numbers, dates/times, price, a preference or complication.
- Distractors: a changed date or price ("the fifteenth, no sorry, the fourteenth"), a rejected option, a mishearing that is repaired.
- Good tags: `specific_detail`, `numbers_dates_times`, `purpose`, `distractor_resolution`, `speaker_attitude` (end of call).

## social_monologue (1 speaker)

- Setting: guide, host, event organiser, facilities briefing, announcement.
- Strong signposting ("First of all...", "If you look at the leaflet...", "One last thing..."). Directions and layout language are fine.
- Distractors: a change of plan or an exception ("Photography is allowed everywhere except..."). Keep them in the audio, not in the options only.
- Good tags: `sequence`, `organisation_signposting`, `specific_detail`, `distractor_resolution`.

## academic_discussion (2-4 speakers)

- Setting: tutor and student(s), group project, feedback, choosing a method or topic. Give each speaker a clear role.
- Real turn-taking: building on a point, polite disagreement, hedging ("I'm not sure I agree", "that's a fair point, but").
  Answers often sit where the group reaches a decision, so include options that are proposed and then rejected.
- Distractors: a view that changes after discussion; two speakers who disagree before one gives way.
- Good tags: `speaker_opinion`, `speaker_attitude`, `inference`, `distractor_resolution`, `purpose`.

## academic_lecture (1 speaker)

- Setting: short lecture on a study-related subject. Structure: introduction, points in sequence, example, conclusion.
- Markers: "First", "A further factor", "As a result", "To sum up". Definitions, cause-effect, contrast, exemplification.
- No chit-chat; no Section-1 style self-correction. Difficulty is lexical and structural. A "or rather" reframing is fine.
- Good tags: `gist`, `organisation_signposting`, `paraphrase_recognition`, `inference`, `specific_detail`.

## Speaker roles and the later TTS step

Give every speaker a short `role` (for example `hotel receptionist`, `tutor`, `lecturer`). `scripts/export_tts_scenario.py` uses it
to build the TTS audio profile; voices are assigned from gender automatically. Vary accents and genders across the bank.
