# Remaining risks and limitations

1. **No learner-response data.** Difficulty, CEFR level, discrimination and distractor attractiveness are all unmeasured. Every CEFR label is the author's intent; the QA heuristic agrees exactly with it for only 517/1610 = 32.1% of questions (within one level 72%, Spearman 0.649); that disagreement is noise-dominated and must not be read as "the labels are wrong".
2. **Single-model authoring and review.** The bank, the distractor rewrites and the manual false-positive overrides were all produced by the same LLM. Nothing has been checked by a human or a second independent system; all 488 rewritten questions are in the P2 queue.
3. **Residual answer-position cues.** After rewriting, the key is still the longest option in 594/1152 plain-MC items (52%; chance is about 33%, before the rewrite 69%). A learner who always picks the longest option still gains an advantage.
4. **Thin sub-skill coverage.** Primary sub-skills: detail_retrieval 823, claim_verification 235, information_tracking 211, paraphrase_recognition 155, stance_attitude 146, inference 23, main_idea_gist 12, discourse_structure 5. Inference, main idea and discourse structure cannot support sub-skill claims; A1/A2 listening is detail retrieval only.
5. **Placement extremes.** A placement exam contains only 3 A1 and 3-7 C2 questions; that is presence, not reliable measurement. Level exams are strictly level-pure by assumption; a "target level plus adjacent items" design would need new parts.
6. **Blueprint constraints are mostly satisfied by construction.** Assessment exams violated no constraint even without enforcement; the enforcement only changes placement (topic repetition). Stronger constraints need a bigger bank.
7. **Text length.** Passages are 120-760 words; reading passages are far shorter than IELTS (about 150-500). Lower bounds in `config/blueprint.json` profiles were relaxed to fit the authored texts; this was a content decision, not a measurement one.
8. **No audio.** 70 listening parts reference mp3 files that do not exist; transcripts and audio cannot be cross-checked and the construct changes (reading a transcript).
9. **Rule-based semantics.** The semantic review is lexical/structural. It cannot prove that an item is valid; passing it means "no rule fired". Evidence quotes exist in the source but may not entail the key.
10. **Diagnostics are hypotheses.** Only 541/3329 = 16.3% distractors have a text-grounded, medium-confidence explanation; none are validated.
11. **Learning objectives are placeholders** (generated sub-skill x level strings). Lesson mapping is empty because no lesson bank exists in the project.
12. **Question status.** All content is `validated` (script) - none is `reviewed`/`approved`. `--stamp` re-validated edited parts automatically.
13. **Duplicate detection** found no near-duplicate questions or sources at the chosen thresholds (prompt+key Jaccard >= 0.75, 5-gram source overlap >= 0.15); this is a statement about those thresholds only. `reports/duplicate_candidates.csv` is therefore header-only.
14. **Pass mark and indicative-level rules** (60 %) are prototype values taken from the project, not validated.
