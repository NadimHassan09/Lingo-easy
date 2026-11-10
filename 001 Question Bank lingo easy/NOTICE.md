# Attribution

Parts of this kit are adapted from or include material from **LuchoBazz/ielts-ai-dataset**
(https://github.com/LuchoBazz/ielts-ai-dataset), licensed under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.

- `config/tts-base-config.json` is an unmodified copy of that repo's `config/tts-config.json` (voice library and delivery presets).
- `.agent/skills/lingoeasy-listening-generator/references/part-type-playbook.md` adapts the structure and conventions of that repo's
  `skills/ielts-listening-generator` (changes: rewritten wording, profile-based distractor rules, multiple-choice conversion).
- `scripts/export_tts_scenario.py` produces configs consumable by that repo's `scripts/generate-tts/` scripts.

Everything else (schema, validator, blueprint, taxonomy, both generator skills, calibration guide, examples) was written for Lingo Easy.
Keep this notice with the kit and in the project's credits if you ship content derived from it.

## Writing and Speaking generators
`.agent/skills/lingoeasy-writing-generator/` adapts the *approach* of that repository's Writing generator prompts (`prompts/*/ielts-writing-generator.md`: tasks with title, suggested time, minimum words, a target band that governs topic abstraction, vocabulary and cognitive demand, and a described stimulus for data tasks) and the structure of its `skills/ielts-listening-generator/SKILL.md`.
`.agent/skills/lingoeasy-speaking-generator/` follows the same skill structure; the repository has no Speaking generator, so the Speaking design (IELTS Part 1/2/3-inspired formats adapted to CEFR A1-C2) is original. Wording is original; no prompt text was copied. The Lingo Easy task schema, CEFR calibration, evaluation blueprints and text-only Speaking rules were written for this project.

