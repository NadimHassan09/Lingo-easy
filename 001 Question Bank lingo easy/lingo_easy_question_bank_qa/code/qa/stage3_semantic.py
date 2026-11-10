"""Stage 3: automated semantic review of every question (rule-based, NOT an LLM or human judgement).

Each record gets: semantic_status, three 0-100 sub-scores (rule-derived), overall_semantic_confidence, findings,
evidence_checked, recommended_action. Scores are heuristics for triage, not probabilities of correctness.
"""
import json
import re
import sys
from collections import Counter

from .common import *  # noqa: F401,F403

REVIEWER_TYPE = "automated"
REVIEW_METHOD = "rule-based lexical/structural checks (qa/stage3_semantic.py); no semantic understanding"
EXTREME = re.compile(r"\b(completely|totally|entirely|absolutely|always|never|useless|nothing|impossible|everyone|nobody|no one|a waste of|all of|none of)\b", re.I)
NEG = re.compile(r"\b(not|never|no|none|nothing|nobody|cannot|can't|isn't|aren't|doesn't|don't|won't)\b", re.I)
NUMW = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
       "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30, "fortieth": 40}


def numbers_in(text):
    """Set of numeric values mentioned as digits or number words ('twenty-four', 'three hundred and sixty', 'five thousand eight hundred')."""
    t = text.lower().replace(",", "")
    vals = set(int(x) for x in re.findall(r"[0-9]+", t))
    words = re.findall(r"[a-z]+", t.replace("-", " "))
    n = len(words)

    def small(i):  # 0..99 -> (value, next_i) or (None, i)
        if i < n and words[i] in ORD:
            return ORD[words[i]], i + 1
        if i < n and words[i] in NUMW:
            if NUMW[words[i]] >= 20 and i + 1 < n and words[i + 1] in ORD and ORD[words[i + 1]] < 10:
                return NUMW[words[i]] + ORD[words[i + 1]], i + 2
            v = NUMW[words[i]]
            if v >= 20 and i + 1 < n and words[i + 1] in NUMW and NUMW[words[i + 1]] < 10:
                return v + NUMW[words[i + 1]], i + 2
            return v, i + 1
        return None, i

    def below_1000(i):
        if i < n and words[i] == "a" and i + 1 < n and words[i + 1] == "hundred":
            v, j = 1, i + 1
        else:
            v, j = small(i)
            if v is None:
                return None, i
        if j < n and words[j] == "hundred":
            v, j = v * 100, j + 1
            k = j + 1 if j < n and words[j] == "and" else j
            r, k2 = small(k)
            if r is not None:
                v, j = v + r, k2
        return v, j

    i = 0
    while i < n:
        v, j = below_1000(i)
        if v is None:
            if words[i] in ("hundred", "thousand"):
                vals.add(100 if words[i] == "hundred" else 1000)
            i += 1
            continue
        if j < n and words[j] == "thousand":
            v, j = v * 1000, j + 1
            k = j + 1 if j < n and words[j] == "and" else j
            r, k2 = below_1000(k)
            if r is not None:
                v, j = v + r, k2
        vals.add(v)
        i = max(j, i + 1)
    return vals


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


OVR = {}
_f = ROOT / "qa" / "manual_overrides.json"
if _f.exists():
    OVR = json.loads(_f.read_text(encoding="utf-8")).get("overrides", {})


def review(rec, part):
    flags = []  # (code, dimension, weight, severity, detail)
    qid, skill = rec["question_id"], rec["modality"]
    src_units = source_units(part)
    src = source_text(part)
    opts = rec["options"]
    ans_i = "ABCD".index(rec["answer_id"])
    correct = opts[ans_i]
    wrong = [o for i, o in enumerate(opts) if i != ans_i]
    ev = rec["evidence"]
    is_ng = correct == "Not Given"
    fmt = rec["question_type"]
    tfng = fmt in ("true_false_not_given", "yes_no_not_given")
    matching = fmt.startswith("matching")
    checked = []
    # --- source alignment
    if ev:
        checked.append({"source": rec["part_id"], "unit": ev.get("paragraph"), "quote": ev["quote"]})
    if is_ng:
        best = 0.0
        stoks = set(toks(rec["prompt"]))
        for _, text in src_units:
            for s in sentences(text):
                if stoks:
                    best = max(best, len(stoks & set(toks(s))) / len(stoks))
        if best >= 0.75:
            flags.append(("ng_statement_may_be_addressed", "source", 35, "major", f"{best:.0%} of statement words occur in one source sentence"))
    elif tfng and ev:
        ov = len(set(toks(rec["prompt"])) & set(toks(ev["quote"]))) / max(1, len(set(toks(rec["prompt"]))))
        if ov < 0.15:
            flags.append(("weak_statement_evidence_link", "source", 10, "minor", f"overlap {ov:.0%} (may be legitimate paraphrase)"))
    elif not tfng and not matching:
        base = set(toks(correct))
        support = set(toks(ev["quote"] + " " + rec["explanation"])) if ev else set()
        if base and len(base & support) / len(base) < 0.2 and not (numbers_in(correct) & numbers_in(src)):
            flags.append(("correct_option_lexically_unsupported", "source", 15, "minor", "no lexical overlap with evidence/explanation (paraphrase or unsupported)"))
    if skill == "listening" or not tfng:
        nums = numbers_in(correct)
        if nums and nums != {1} and not (nums & numbers_in(src)) and not tfng and not matching:
            flags.append(("number_not_in_source", "source", 30, "major", f"numbers {sorted(nums)} not found in source"))
    names = [] if (tfng or matching) else [w for w in re.findall(r"(?<!^)(?<![.!?] )\b[A-Z][a-z]{2,}\b", correct)]
    for nm in names:
        if nm.lower() not in src.lower():
            flags.append(("name_not_in_source", "source", 20, "major", nm))
    # --- answer validity
    if not tfng and not matching and ev:
        ctoks = set(toks(correct))
        etoks = set(toks(ev["quote"]))
        for w in wrong:
            wt = set(toks(w))
            if len(wt & etoks) >= 2 and len(wt & etoks) > len(ctoks & etoks):
                flags.append(("distractor_closer_to_evidence_than_key", "answer", 30, "major", w))
    if not tfng and not matching:
        for w in wrong:
            if len(norm(w).split()) >= 3 and norm(w) in norm(src):
                flags.append(("distractor_verbatim_in_source", "answer", 5 if not (ev and norm(w) in norm(ev["quote"])) else 30,
                              "minor" if not (ev and norm(w) in norm(ev["quote"])) else "major", w))
    if matching and ev and ev.get("paragraph"):
        right_para = ev["paragraph"]
        stoks = set(toks(rec["prompt"]))
        for lab, text in src_units:
            if lab != right_para and "Paragraph " + lab in opts and stoks:
                best = max((len(stoks & set(toks(s))) / len(stoks) for s in sentences(text)), default=0)
                if best >= 0.6:
                    flags.append(("matching_distractor_paragraph_overlaps_statement", "answer", 25, "major", f"paragraph {lab}: {best:.0%}"))
    # --- construction
    lens = [len(o) for o in opts]
    if not tfng and not matching:
        mean_w = sum(len(w) for w in wrong) / len(wrong)
        if len(correct) == max(lens) and len(correct) >= 1.3 * mean_w and len(correct) - mean_w >= 6:
            flags.append(("length_cue_correct_option_longest", "construction", 15, "major", f"correct {len(correct)} chars vs distractors mean {mean_w:.0f}"))
        if max(lens) > 3 * max(1, min(lens)) and max(lens) - min(lens) > 20:
            flags.append(("option_length_imbalance", "construction", 5, "minor", f"{min(lens)}-{max(lens)} chars"))
        hit = [w for w in wrong if EXTREME.search(w)]
        if hit:
            flags.append(("extreme_wording_in_distractor", "construction", 20 if rec["original_cefr"] in ("B2", "C1", "C2") else 8,
                          "major" if rec["original_cefr"] in ("B2", "C1", "C2") else "minor", "; ".join(hit)))
        if len(NEG.findall(rec["prompt"])) + len(NEG.findall(correct)) >= 2:
            flags.append(("possible_double_negative", "construction", 10, "minor", rec["prompt"]))
        ctoks = set(toks(correct))
        if ctoks and len(ctoks & set(toks(rec["prompt"]))) / len(ctoks) >= 0.8 and "_" not in rec["prompt"]:
            flags.append(("key_repeats_prompt_words", "construction", 10, "minor", "answer largely echoes the question"))
    if not tfng and not matching and not rec["prompt"].strip().endswith(("?", ".", "_", ")")) and "_____" not in rec["prompt"]:
        flags.append(("prompt_punctuation", "construction", 3, "minor", rec["prompt"][-20:]))
    # --- scoring
    def dim(d):
        return max(0, 100 - sum(f[2] for f in flags if f[1] == d))
    s_src, s_ans, s_con = dim("source"), dim("answer"), dim("construction")
    overall = round(0.4 * s_src + 0.35 * s_ans + 0.25 * s_con)
    ov = OVR.get(qid)
    if ov:
        flags = [(f[0], f[1], f[2], "minor", f[4] + " [downgraded after manual look: " + ov["note"] + "]") if f[0] in ov["codes"] else f for f in flags]
    major = [f for f in flags if f[3] == "major"]
    status = "human_review" if major else "pass"
    return {
        "question_id": qid, "uuid": rec["uuid"], "source_file": rec["source_file"], "part_id": rec["part_id"], "bank": rec["bank"],
        "semantic_status": status, "source_alignment_score": s_src, "answer_validity_score": s_ans, "question_construction_score": s_con,
        "overall_semantic_confidence": overall,
        "findings": [{"code": f[0], "dimension": f[1], "severity": f[3], "detail": f[4]} for f in flags],
        "evidence_checked": checked,
        "recommended_action": ("rewrite distractors / review key" if major else "none (automated checks only; not a validation of meaning)"),
        "changes_applied": [], "manual_override": bool(ov), "reviewer_type": REVIEWER_TYPE, "review_method": REVIEW_METHOD, "review_version": REVIEW_VERSION,
    }


def run(out=None):
    out = out or REPORTS
    entries = load_parts()
    byid = {e["part"]["id"]: e["part"] for e in entries}
    from .stage1_inventory_integrity import question_records
    recs = question_records(entries)
    rows = [review(r, byid[r["part_id"]]) for r in recs]
    changes = {}
    logf = AUDIT / "question_change_log.jsonl"
    if logf.exists():
        for line in open(logf, encoding="utf-8"):
            c = json.loads(line)
            changes.setdefault(c["question_id"], []).append({"patch": c["patch_file"], "fields": c["fields_modified"], "reason": c["reason"]})
    for r in rows:
        ch = changes.get(r["question_id"])
        if ch:
            r["changes_applied"] = ch
            if r["semantic_status"] == "pass":
                r["semantic_status"] = "fix_applied"
                r["recommended_action"] = "distractors rewritten (LLM-assisted); needs independent human confirmation"
    write_jsonl(out / "semantic_review.jsonl", rows)
    flat = []
    for r in rows:
        x = dict(r)
        x["findings"] = "; ".join(f"{f['code']}[{f['severity']}]: {f['detail']}" for f in r["findings"])
        x["evidence_checked"] = "; ".join(f"{e['source']}/{e['unit']}: {e['quote']}" for e in r["evidence_checked"])
        x["changes_applied"] = "; ".join(f"{c['patch']}: {','.join(c['fields'])}" for c in r["changes_applied"])
        flat.append(x)
    write_csv(out / "semantic_review.csv", flat)
    c = Counter(r["semantic_status"] for r in rows)
    codes = Counter(f["code"] for r in rows for f in r["findings"])
    print(dict(c), codes.most_common(12))
    return rows


if __name__ == "__main__":
    run()
