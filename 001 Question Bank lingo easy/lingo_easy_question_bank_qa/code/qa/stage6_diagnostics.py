"""Stage 6: distractor diagnostics (hypotheses) and the v2 question-record export.

Every diagnostic is a HYPOTHESIS about why a learner might pick an option. Two evidence classes are used:
  text_grounded    : derived from overlap between the option and a specific source sentence (quoted in evidence_basis)
  item_structure   : derived only from the item format (e.g. choosing 'Not Given' when the answer is True); generic, never specific
Confidence is categorical (high/medium/low); nothing here is calibrated against learner responses.
"""
import json
import re
from collections import Counter

from .common import *  # noqa: F401,F403
from .stage1_inventory_integrity import question_records
from .stage3_semantic import numbers_in, sentences

ERR = "error_tags"


def best_sentence(opt_toks, part):
    best, where, score = "", None, 0.0
    for label, text in source_units(part):
        for s in sentences(text):
            st = set(toks(s))
            if not opt_toks:
                continue
            sc = len(opt_toks & st) / len(opt_toks)
            if sc > score:
                best, where, score = s, label, sc
    return best, where, score


def diagnose(rec, part, meta):
    out = []
    fmt, tag, skill = rec["question_type"], rec["skill_tag"], rec["modality"]
    ans_i = "ABCD".index(rec["answer_id"])
    ev = rec["evidence"]
    ev_unit = ev.get("paragraph") if ev else None
    prim = meta["primary_subskill"]
    for i, opt in enumerate(rec["options"]):
        oid = "ABCD"[i]
        if i == ans_i:
            out.append({"option_id": oid, "is_correct": True, "rationale": rec["explanation"], "error_tags": [], "targeted_subskills": [prim],
                        "diagnostic_confidence": "n/a", "evidence_basis": (ev or {}).get("quote", "statement is not addressed in the source"), "evidence_class": "explanation_field"})
            continue
        key = rec["answer_text"]
        if fmt in ("true_false_not_given", "yes_no_not_given"):
            yes = {"True", "Yes"}
            no = {"False", "No"}
            ng = "Not Given"
            if opt == ng and key != ng:
                tags, why = ["evidence_not_located"], "Learner may not have found the sentence that settles the statement and judged it unaddressed."
            elif key == ng and opt != ng:
                tags, why = ["unsupported_inference"], "Learner may have assumed information the source does not give."
            elif (key in yes and opt in no) or (key in no and opt in yes):
                tags, why = ["negation_or_contradiction_missed", "paraphrase_not_recognised"], "Learner may have missed a negation or a paraphrase and read the source as saying the opposite."
            else:
                tags, why = ["insufficient_evidence_to_classify"], "No specific hypothesis."
            out.append({"option_id": oid, "is_correct": False, "rationale": why, "error_tags": tags, "targeted_subskills": [prim],
                        "diagnostic_confidence": "medium" if tags != ["insufficient_evidence_to_classify"] else "low",
                        "evidence_basis": (ev or {}).get("quote", ""), "evidence_class": "item_structure"})
            continue
        if fmt.startswith("matching"):
            stoks = set(toks(rec["prompt"]))
            lab = opt.replace("Paragraph ", "")
            text = dict(source_units(part)).get(lab, "")
            best, _, sc = best_sentence(stoks, {"skill": "reading", "passage": {"paragraphs": [{"label": lab, "text": text}]}}) if text else ("", None, 0)
            if sc >= 0.4:
                out.append({"option_id": oid, "is_correct": False, "rationale": f"Paragraph {lab} shares topic words with the statement (best sentence overlap {sc:.0%}), so it can look right on a topic match.",
                            "error_tags": ["topic_association_guess", "attention_to_wrong_part_of_source"], "targeted_subskills": ["discourse_structure"],
                            "diagnostic_confidence": "medium", "evidence_basis": best, "evidence_class": "text_grounded"})
            else:
                out.append({"option_id": oid, "is_correct": False, "rationale": "Paragraph does not overlap with the statement; likely a guess.", "error_tags": ["insufficient_evidence_to_classify"],
                            "targeted_subskills": ["discourse_structure"], "diagnostic_confidence": "low", "evidence_basis": "", "evidence_class": "item_structure"})
            continue
        # multiple choice / sentence completion
        otoks = set(toks(opt))
        best, where, sc = best_sentence(otoks, part)
        tags, why, conf, cls, basis = [], "", "low", "item_structure", ""
        num_opt, num_key = numbers_in(opt), numbers_in(key or "")
        if num_opt and num_key and num_opt != num_key:
            tags = ["number_or_time_confusion"]
            hit = best if sc >= 0.5 else ""
            why = "Learner may have confused this figure/time with the one asked about" + (" (it is mentioned elsewhere in the source)." if hit else ".")
            conf, cls, basis = ("medium", "text_grounded", hit) if hit else ("low", "item_structure", "")
        elif sc >= 0.6:
            same = (where == ev_unit) if ev_unit else None
            if skill == "listening" and tag == "distractor_resolution":
                tags = ["confusion_proposed_vs_confirmed"]
                why = "This option is mentioned in the recording before or around the confirmed information, so it can be chosen by a learner who does not track the correction."
            elif same:
                tags = ["paraphrase_not_recognised", "missed_explicit_detail"]
                why = "This option reuses words from the very sentence that holds the answer, so it can be chosen on a partial lexical match."
            else:
                tags = ["attention_to_wrong_part_of_source"]
                why = f"This option reuses words from a different part of the source ({where}), so it can be chosen by a learner who attends to the wrong passage."
            conf, cls, basis = "medium", "text_grounded", best
        elif sc >= 0.35:
            tags = ["attention_to_wrong_part_of_source", "topic_association_guess"]
            why = "Partly overlaps with the source; may attract a learner relying on topic words."
            conf, cls, basis = "low", "text_grounded", best
        else:
            if prim in ("inference", "stance_attitude", "main_idea_gist"):
                tags = ["unsupported_inference"] + (["attitude_misread"] if prim == "stance_attitude" else [])
                why = "The source does not support this; it is a plausible-sounding conclusion, so it tests whether the learner stays within the evidence."
            else:
                tags = ["topic_association_guess"]
                why = "Not supported by the source; may attract a learner choosing by topic or guessing."
            conf, cls, basis = "low", "item_structure", ""
        out.append({"option_id": oid, "is_correct": False, "rationale": why, "error_tags": tags,
                    "targeted_subskills": [prim], "diagnostic_confidence": conf, "evidence_basis": basis, "evidence_class": cls})
    return out


def run(out=None):
    out = out or REPORTS
    entries = load_parts()
    byid = {e["part"]["id"]: e["part"] for e in entries}
    meta_all = json.loads((ROOT / "config" / "question_meta_v2.json").read_text(encoding="utf-8"))["questions"]
    recs = question_records(entries)
    rows, v2 = [], []
    for r in recs:
        m = meta_all[r["uuid"]]
        dg = diagnose(r, byid[r["part_id"]], m)
        for d in dg:
            rows.append({"question_id": r["question_id"], "uuid": r["uuid"], "bank": r["bank"], "modality": r["modality"], "primary_subskill": m["primary_subskill"],
                         "option_id": d["option_id"], "option_text": r["options"]["ABCD".index(d["option_id"])], "is_correct": d["is_correct"], "rationale": d["rationale"],
                         "error_tags": ";".join(d["error_tags"]), "targeted_subskills": ";".join(d["targeted_subskills"]), "diagnostic_confidence": d["diagnostic_confidence"],
                         "evidence_class": d["evidence_class"], "evidence_basis": d["evidence_basis"],
                         "meaningful": (not d["is_correct"]) and d["evidence_class"] == "text_grounded" and d["diagnostic_confidence"] in ("medium", "high") and bool(d["evidence_basis"])})
        v2.append({"schema_version": "2.0", "question_id": r["question_id"], "uuid": r["uuid"], "part_id": r["part_id"], "part_uuid": r["part_uuid"],
                   "source_file": r["source_file"], "bank": r["bank"], "assessment_type": r["assessment_type"], "modality": r["modality"],
                   "item_format": r["question_type"], "prompt": r["prompt"], "options": [{"id": "ABCD"[i], "text": t} for i, t in enumerate(r["options"])],
                   "answer": r["answer_id"], "evidence": r["evidence"], "explanation": r["explanation"],
                   "level": {"original_cefr": r["original_cefr"], "original_band": r["original_band"], "text_cefr": r["text_cefr"]},
                   "skills": {"original_skill_tag": r["skill_tag"], "primary_subskill": m["primary_subskill"], "recommended_primary_subskill": m["recommended_primary_subskill"],
                              "secondary_subskills": m["secondary_subskills"], "cognitive_process": m["cognitive_process"], "answer_type": m["answer_type"],
                              "validation": m["subskill_validation"]},
                   "topic": r["topic"], "language_focus": r["language_focus"], "distractor_diagnostics": dg,
                   "review": {"review_version": REVIEW_VERSION, "diagnostics_class": "hypotheses (rule-based); not validated on learner data"}})
    write_csv(out / "distractor_diagnostics.csv", rows)
    OUT.joinpath("exports").mkdir(exist_ok=True)
    write_jsonl(OUT / "exports" / "question_records_v2.jsonl", v2)
    side = {r["uuid"]: {"question_id": r["question_id"], "distractor_diagnostics": {d["option_id"]: {k: d[k] for k in ("is_correct", "error_tags", "targeted_subskills", "diagnostic_confidence", "evidence_class")} for d in r["distractor_diagnostics"]}} for r in v2}
    write_json(ROOT / "config" / "distractor_diagnostics_v2.json", {"_note": "Generated sidecar (qa/stage6_diagnostics.py). Static, rule-based diagnostic HYPOTHESES keyed by question UUID; contains no learner data.", "questions": side})
    wrong = [x for x in rows if not x["is_correct"]]
    meaningful = [x for x in wrong if x["meaningful"]]
    summ = {"distractors_total": len(wrong), "distractors_meaningful_text_grounded_medium_or_high": len(meaningful),
            "by_evidence_class": dict(Counter(x["evidence_class"] for x in wrong)), "by_confidence": dict(Counter(x["diagnostic_confidence"] for x in wrong)),
            "top_error_tags": Counter(t for x in wrong for t in x["error_tags"].split(";") if t).most_common(10)}
    write_json(out / "distractor_diagnostics_summary.json", summ)
    print(summ["distractors_total"], summ["distractors_meaningful_text_grounded_medium_or_high"], summ["by_confidence"])
    return summ


if __name__ == "__main__":
    run()
