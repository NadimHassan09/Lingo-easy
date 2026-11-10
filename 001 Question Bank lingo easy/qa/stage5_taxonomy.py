"""Stage 5: normalised skill taxonomy, tag mapping and per-question sub-skill validation (rule-based)."""
import re
from collections import Counter, defaultdict

from .common import *  # noqa: F401,F403
from .stage1_inventory_integrity import question_records, TAX
from .stage3_semantic import numbers_in, sentences
from .stage4_cefr import evidence_sentence

SUBSKILLS = {
    "detail_retrieval": "Locate explicit information (name, number, time, place, fact) stated in the source.",
    "paraphrase_recognition": "Match information to a restated (paraphrased) version of it.",
    "main_idea_gist": "Identify the overall topic, main point or conclusion of a text or recording.",
    "inference": "Draw a conclusion that is implied but not stated.",
    "stance_attitude": "Identify a speaker's or writer's opinion, attitude or claim.",
    "discourse_structure": "Follow how a text/recording is organised (signposting, sequence, paragraph function).",
    "purpose_function": "Identify why something is said or included.",
    "reference_resolution": "Resolve what a pronoun or reference expression points to.",
    "vocabulary_in_context": "Infer the meaning of a word or phrase from context.",
    "claim_verification": "Judge whether a statement agrees with, contradicts, or is not addressed by the source.",
    "information_tracking": "Select the final/confirmed information when earlier options are changed, corrected or rejected.",
}
COGNITIVE = {"retrieve": "Find explicit information.", "interpret": "Understand restated or implied-by-wording meaning.",
             "infer": "Go beyond the text to implied meaning.", "integrate": "Combine information across parts of the source.",
             "evaluate": "Judge a claim against the source."}
ERRORS = {
    "missed_explicit_detail": "Failed to locate or notice information stated explicitly.",
    "attention_to_wrong_part_of_source": "Picked information from a different part of the source than the one asked about.",
    "confusion_proposed_vs_confirmed": "Chose an option that was proposed, rejected or corrected before the final information.",
    "confusion_between_speakers": "Attributed information to the wrong speaker.",
    "paraphrase_not_recognised": "Did not recognise a restated version of the information.",
    "unsupported_inference": "Chose a plausible but unsupported conclusion.",
    "reference_misinterpretation": "Misread what a reference word points to.",
    "main_idea_vs_detail_confusion": "Took a supporting detail for the main idea (or vice versa).",
    "attitude_misread": "Misjudged the speaker's/writer's stance.",
    "vocabulary_misunderstanding": "Misunderstood a word or phrase.",
    "grammatical_misinterpretation": "Misread a grammatical structure (e.g. negation, comparison).",
    "number_or_time_confusion": "Confused similar numbers, times, dates or amounts.",
    "negation_or_contradiction_missed": "Missed that the source contradicts the statement.",
    "evidence_not_located": "Could not find the relevant evidence (e.g. chose Not Given when it is stated).",
    "topic_association_guess": "Chose an option because it is topically related, without evidence.",
    "insufficient_evidence_to_classify": "No reliable hypothesis can be made from the item alone.",
}
# original tag -> (primary subskill, cognitive process, what the ORIGINAL tag actually describes, note)
TAGMAP = {
    ("listening", "gist"): ("main_idea_gist", "integrate", "sub-skill", ""),
    ("listening", "specific_detail"): ("detail_retrieval", "retrieve", "sub-skill", ""),
    ("listening", "numbers_dates_times"): ("detail_retrieval", "retrieve", "content/answer type", "Describes the kind of answer (numeric), not a separate skill."),
    ("listening", "speaker_opinion"): ("stance_attitude", "interpret", "sub-skill", "Overlaps with speaker_attitude."),
    ("listening", "speaker_attitude"): ("stance_attitude", "infer", "sub-skill", "Overlaps with speaker_opinion."),
    ("listening", "purpose"): ("purpose_function", "interpret", "sub-skill", ""),
    ("listening", "inference"): ("inference", "infer", "cognitive process", ""),
    ("listening", "sequence"): ("discourse_structure", "integrate", "sub-skill", ""),
    ("listening", "paraphrase_recognition"): ("paraphrase_recognition", "interpret", "sub-skill", ""),
    ("listening", "distractor_resolution"): ("information_tracking", "integrate", "item-construction feature / test-taking strategy", "Describes how the item is built (a corrected/rejected option), not a language skill."),
    ("listening", "organisation_signposting"): ("discourse_structure", "integrate", "linguistic feature", ""),
    ("reading", "main_idea"): ("main_idea_gist", "integrate", "sub-skill", ""),
    ("reading", "specific_detail"): ("detail_retrieval", "retrieve", "sub-skill", ""),
    ("reading", "inference"): ("inference", "infer", "cognitive process", ""),
    ("reading", "writer_claim"): ("stance_attitude", "evaluate", "sub-skill", "In this bank it is used with Yes/No/Not Given items."),
    ("reading", "fact_check"): ("claim_verification", "evaluate", "question format", "Describes the True/False/Not Given format."),
    ("reading", "vocabulary_in_context"): ("vocabulary_in_context", "interpret", "sub-skill", "Not used in the current bank."),
    ("reading", "reference_resolution"): ("reference_resolution", "interpret", "sub-skill", "Not used in the current bank."),
    ("reading", "paraphrase_matching"): ("paraphrase_recognition", "interpret", "sub-skill", "Used for matching-information items as well as MCQ."),
    ("reading", "text_organisation"): ("discourse_structure", "integrate", "sub-skill", ""),
    ("reading", "heading_matching"): ("discourse_structure", "integrate", "question format", "Describes the matching-headings format; not used."),
    ("reading", "summary_gap"): ("detail_retrieval", "retrieve", "question format", "Used for sentence-completion items; the format, not a skill."),
}
OPINION_WORDS = re.compile(r"\b(view|opinion|attitude|think|believe|feel|claim|suggest|advise|position|stance|conclude|argue|approve|doubt|worried|concern|reluctant|cautious|sceptic|accept|favour|recommend|regard|consider|agree|certain|support|oppose|says?|states?|admit|implies?|intend|prefer|warn|concede|expect|hope|dismiss)\w*", re.I)
MAIN_WORDS = re.compile(r"\b(main|mainly|overall|sums up|best sums|conclusion|message|about|position)\b", re.I)
ORG_WORDS = re.compile(r"\b(order|organis|why does the (writer|lecturer)|mention|purpose|how is|paragraph|structure)\w*", re.I)
TIME_RE = re.compile(r"\d[:.]\d\d|o'clock|\b(am|pm)\b|morning|afternoon|evening|night|weekend|\b(mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(january|february|march|april|may|june|july|august|september|october|november|december)\b|\bweeks?\b|\bhours?\b|\bminutes?\b|\bdays?\b|\byears?\b|\bmonths?\b|\bper cent\b", re.I)


def answer_type(rec):
    a, p = rec["answer_text"] or "", rec["prompt"].lower()
    if rec["question_type"] in ("true_false_not_given", "yes_no_not_given"):
        return "judgement"
    if rec["question_type"].startswith("matching"):
        return "location_of_information"
    if TIME_RE.search(a) and (re.search(r"\d", a) or numbers_in(a)):
        return "time_or_date"
    if numbers_in(a):
        return "number_or_amount"
    if p.startswith("why") or "reason" in p:
        return "reason"
    if p.startswith("who"):
        return "person"
    if p.startswith("where"):
        return "place"
    if p.startswith("what") or p.startswith("which"):
        return "thing_or_event"
    return "other"


def validate(rec, part, tag_row):
    prim = tag_row[0]
    tag = rec["skill_tag"]
    ans = set(toks(rec["answer_text"] or ""))
    ev_s = evidence_sentence(part, rec["evidence"])
    evt = set(toks(ev_s))
    overlap = len(ans & evt) / len(ans) if ans and evt else None
    src = set(toks(source_text(part)))
    wrong = [o for i, o in enumerate(rec["options"]) if i != "ABCD".index(rec["answer_id"])]
    fmt = rec["question_type"]
    checks = []  # (check, result, detail, recommended_primary or None)
    if tag == "numbers_dates_times":
        ok = bool(numbers_in(rec["answer_text"] or "")) or bool(TIME_RE.search(rec["answer_text"] or ""))
        checks.append(("answer_is_numeric_or_time", "consistent" if ok else "inconsistent", rec["answer_text"], None if ok else "detail_retrieval"))
    if tag in ("paraphrase_matching", "paraphrase_recognition"):
        if overlap is None:
            checks.append(("paraphrase_distance", "not_verifiable", "no evidence sentence", None))
        elif overlap >= 0.6:
            checks.append(("paraphrase_distance", "inconsistent", f"answer reuses {overlap:.0%} of evidence words: looks like direct retrieval", "detail_retrieval"))
        else:
            checks.append(("paraphrase_distance", "consistent", f"answer reuses {overlap:.0%} of evidence words", None))
    if tag == "specific_detail" and overlap is not None and overlap < 0.2 and fmt == "multiple_choice":
        checks.append(("detail_has_lexical_match", "inconsistent", f"answer shares only {overlap:.0%} of words with evidence: probably paraphrase", "paraphrase_recognition"))
    if tag == "inference":
        if overlap is not None and overlap >= 0.8:
            checks.append(("inference_not_explicit", "inconsistent", f"answer restates evidence ({overlap:.0%} word overlap)", "paraphrase_recognition"))
        else:
            checks.append(("inference_not_explicit", "consistent" if overlap is not None else "not_verifiable", f"overlap {overlap}", None))
    if tag in ("speaker_opinion", "speaker_attitude", "writer_claim"):
        ok = bool(OPINION_WORDS.search(rec["prompt"])) or bool(OPINION_WORDS.search(ev_s))
        checks.append(("stance_cue_in_prompt_or_evidence", "consistent" if ok else "inconsistent", rec["prompt"], None if ok else "detail_retrieval"))
    if tag in ("main_idea", "gist"):
        ok = bool(MAIN_WORDS.search(rec["prompt"]))
        checks.append(("prompt_asks_for_overall_point", "consistent" if ok else "inconsistent", rec["prompt"], None if ok else "detail_retrieval"))
    if tag in ("text_organisation", "organisation_signposting", "sequence", "purpose"):
        ok = bool(ORG_WORDS.search(rec["prompt"]))
        checks.append(("prompt_asks_about_organisation_or_purpose", "consistent" if ok else "not_verifiable", rec["prompt"], None))
    if tag == "distractor_resolution":
        grounded = [w for w in wrong if len(set(toks(w))) and len(set(toks(w)) & src) / len(set(toks(w))) >= 0.6]
        checks.append(("distractor_actually_mentioned_in_source", "consistent" if grounded else "inconsistent",
                       f"{len(grounded)} of {len(wrong)} distractors have >=60% of their content words in the source", None if grounded else "detail_retrieval"))
    if tag == "fact_check":
        ok = fmt in ("true_false_not_given", "yes_no_not_given")
        checks.append(("tag_matches_tfng_format", "consistent" if ok else "inconsistent", fmt, None if ok else "detail_retrieval"))
    if tag == "summary_gap":
        ok = fmt == "sentence_completion"
        checks.append(("tag_matches_sentence_completion", "consistent" if ok else "inconsistent", fmt, None if ok else "detail_retrieval"))
    if fmt.startswith("matching") and tag not in ("paraphrase_matching", "inference", "detail_retrieval"):
        checks.append(("matching_item_tag", "inconsistent", f"matching item tagged {tag}", "paraphrase_recognition"))
    if not checks:
        checks.append(("no_automatable_check", "not_verifiable", tag, None))
    return checks


def secondary(rec, prim, checks):
    sec = []
    if rec["skill_tag"] == "numbers_dates_times":
        sec.append("detail_retrieval") if prim != "detail_retrieval" else None
    if rec["skill_tag"] == "distractor_resolution":
        sec.append("detail_retrieval")
    if rec["question_type"] in ("true_false_not_given", "yes_no_not_given") and prim != "claim_verification" and rec["skill_tag"] != "writer_claim":
        sec.append("claim_verification")
    if rec["question_type"] == "matching_information":
        sec.append("discourse_structure")
    return [s for s in dict.fromkeys(sec) if s and s != prim][:2]


def run(out=None):
    out = out or REPORTS
    entries = load_parts()
    byid = {e["part"]["id"]: e["part"] for e in entries}
    recs = question_records(entries)
    meta, val_rows, tag_counts = {}, [], Counter()
    for r in recs:
        part = byid[r["part_id"]]
        prim, cog, dim, note = TAGMAP[(r["modality"], r["skill_tag"])]
        checks = validate(r, part, (prim, cog, dim, note))
        bad = [c for c in checks if c[1] == "inconsistent"]
        rec_prim = bad[0][3] if bad and bad[0][3] else prim
        sec = secondary(r, prim, checks)
        status = "inconsistent" if bad else ("not_verifiable" if all(c[1] == "not_verifiable" for c in checks) else "consistent")
        tag_counts[(r["modality"], r["skill_tag"], status)] += 1
        meta[r["uuid"]] = {"question_id": r["question_id"], "primary_subskill": prim, "recommended_primary_subskill": rec_prim,
                           "secondary_subskills": sec, "cognitive_process": cog, "answer_type": answer_type(r), "item_format": r["question_type"],
                           "original_skill_tag": r["skill_tag"], "subskill_validation": status, "topic": r["topic"], "part_id": r["part_id"],
                           "original_cefr": r["original_cefr"], "modality": r["modality"]}
        for c in checks:
            val_rows.append({"question_id": r["question_id"], "uuid": r["uuid"], "modality": r["modality"], "original_tag": r["skill_tag"],
                             "normalized_primary_subskill": prim, "recommended_primary_subskill": rec_prim if c[1] == "inconsistent" else prim,
                             "secondary_subskills": ";".join(sec), "check": c[0], "result": c[1], "detail": c[2]})
    write_csv(out / "subskill_validation.csv", val_rows)
    map_rows = []
    by_tag = defaultdict(Counter)
    for r in recs:
        by_tag[(r["modality"], r["skill_tag"])][meta[r["uuid"]]["subskill_validation"]] += 1
    for (mod, tag), (prim, cog, dim, note) in TAGMAP.items():
        c = by_tag.get((mod, tag), Counter())
        n = sum(c.values())
        used_in = Counter(r["question_type"] for r in recs if r["modality"] == mod and r["skill_tag"] == tag)
        issue = ""
        if dim != "sub-skill" and dim != "cognitive process":
            issue = f"Tag describes a {dim}, not a sub-skill: {note}"
        elif c.get("inconsistent"):
            issue = f"{c['inconsistent']} of {n} items fail an automated consistency check"
        if n == 0:
            issue = (issue + " | " if issue else "") + "unused in the current bank"
        map_rows.append({"modality": mod, "original_tag": tag, "items_using_tag": n, "original_tag_describes": dim, "normalized_primary_subskill": prim,
                         "default_cognitive_process": cog, "formats_used": dict(used_in), "consistent": c.get("consistent", 0), "inconsistent": c.get("inconsistent", 0),
                         "not_verifiable": c.get("not_verifiable", 0), "issue": issue, "note": note})
    write_csv(out / "skill_tag_mapping.csv", map_rows)
    taxonomy = {
        "version": "1.0", "status": "proposed normalised taxonomy; original skill_tag values are preserved in the bank and mapped here",
        "dimensions": {"skill": ["reading", "listening"], "item_format": ["multiple_choice", "true_false_not_given", "yes_no_not_given", "sentence_completion", "matching_information"]},
        "subskills": [{"id": k, "description": v} for k, v in SUBSKILLS.items()],
        "cognitive_processes": [{"id": k, "description": v} for k, v in COGNITIVE.items()],
        "answer_types": ["time_or_date", "number_or_amount", "reason", "person", "place", "thing_or_event", "judgement", "location_of_information", "other"],
        "content_categories": TAX["topics"],
        "error_categories": [{"id": k, "description": v} for k, v in ERRORS.items()],
        "original_tag_mapping": [{"modality": m, "tag": t, "primary_subskill": v[0], "cognitive_process": v[1], "tag_describes": v[2], "note": v[3]} for (m, t), v in TAGMAP.items()],
        "learning_objectives": [{"id": f"LO.{s}.{lv}", "subskill": s, "cefr": lv,
                                 "description": f"At CEFR {lv}: {SUBSKILLS[s][0].lower()}{SUBSKILLS[s][1:-1]}, using {lv}-level language and text."}
                                for s in SUBSKILLS for lv in CEFR],
        "note_on_learning_objectives": "Placeholder objectives generated from sub-skill x CEFR level; they are NOT validated can-do statements and need curriculum-team review.",
    }
    write_json(OUT / "schemas" / "skill_taxonomy.json", taxonomy)
    write_json(ROOT / "config" / "question_meta_v2.json", {"_note": "Generated sidecar (qa/stage5_taxonomy.py). Static per-question metadata keyed by question UUID. Not learner data.", "questions": meta})
    c = Counter(m["subskill_validation"] for m in meta.values())
    print(dict(c), Counter(m["primary_subskill"] for m in meta.values()).most_common())
    return meta


if __name__ == "__main__":
    run()
