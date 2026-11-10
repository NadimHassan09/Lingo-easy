"""Structural, semantic (rule-based), diversity and CEFR-alignment validation for Writing/Speaking Parts.

Three evidence classes are kept apart and never merged into one "accuracy" figure:
  * structural   - JSON-schema subset + identity/count/consistency rules (hard failures)
  * semantic     - deterministic rules that approximate editorial checks (flags for humans; they cannot prove educational validity)
  * cefr         - independent heuristic estimate (see cefr.py) compared with the target level
LLM review and human review are NOT performed here; the qa block of each part records that honestly.

Usage: python -m productive.validate [--bank productive_bank] [--json]
"""
import argparse
import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import cefr as cefr_mod
from .common import BANK, LEVELS, LV, ROOT, load_json, readability, shared_taxonomy, taxonomy, words

from .minischema import validate as schema_validate  # copy of qa/minischema.py so the package is self-contained

OBJ_VERBS = {"write", "describe", "give", "express", "explain", "compare", "evaluate", "justify", "narrate", "summarise", "summarize", "argue", "construct", "analyse", "analyze",
             "develop", "present", "respond", "answer", "talk", "sustain", "discuss", "ask", "order", "buy", "make", "report", "interpret", "integrate", "adapt", "transform", "draw",
             "handle", "defend", "negotiate", "mediate", "weigh", "tell", "explain", "use", "negotiate", "propose", "state", "organise", "critically", "hold", "produce", "recount", "invite", "request", "build", "locate", "identify", "manage"}
YESNO_START = re.compile(r"^(do|does|did|is|are|was|were|can|could|will|would|have|has|should)\b", re.I)
WH_WORD = re.compile(r"\b(why|how|what|which|who|where|when|explain|describe|tell|suggest|compare|say)\b", re.I)
SENSITIVE = re.compile(r"\b(alcohol|wine|beer|vodka|pork|bacon|dating|boyfriend|girlfriend|sex|sexual|religion|religious|political party|election|gambling|casino|drugs)\b", re.I)
INVITES = re.compile(r"(?i)" + chr(92) + "bdo you (think|believe|agree)" + chr(92) + "b|" + chr(92) + "bor" + chr(92) + "b|to what extent|in what|how ")
WRITE_PACE = (3.0, 14.0)  # words per minute (planning + writing + checking) plausibility band
FORBIDDEN_KEYS = {"answer", "answer_key", "model_answer", "correct_answer", "ideal_answer", "key"}
SCHEMAS = {s: load_json(ROOT / "schemas" / f"{s}_part.schema.json") for s in ("writing", "speaking")}


def schema_errors(part):
    sk = part.get("skill")
    if sk not in SCHEMAS:
        return [f"$: unknown skill {sk!r}"]
    return schema_validate(part, SCHEMAS[sk])


def walk_keys(o, found=None, path=""):
    found = [] if found is None else found
    if isinstance(o, dict):
        for k, v in o.items():
            if k in FORBIDDEN_KEYS and path != "provenance.raw_spec":
                found.append(f"{path}.{k}".lstrip("."))
            if k != "raw_spec":
                walk_keys(v, found, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk_keys(v, found, f"{path}[{i}]")
    return found


def learner_text(part):
    t = part["task"]
    if part["skill"] == "writing":
        return ". ".join([t["prompt"]] + t["required_points"])
    return ". ".join([t["prompt"], t["main_question"]] + t["follow_up_questions"] + (t.get("cue_card", {}).get("points", [])))


def part_findings(part, tax, shared):
    """Return list of (severity, code, detail) for one part. severity: error | warn."""
    f = []
    sk, lv = part["skill"], part["target_cefr"]
    cfg = tax[sk]["levels"][lv]
    t = part["task"]
    add = lambda sev, code, detail: f.append((sev, code, detail))  # noqa: E731
    # identity / consistency ---------------------------------------------------------------
    a = part["assessment"]
    if a["type"] == "assessment" and a["level"] != lv:
        add("error", "assessment_level_mismatch", f"assessment level {a['level']} != target_cefr {lv}")
    if a["type"] == "placement" and a["level"] is not None:
        add("error", "placement_has_level", "placement parts must not carry a single assessment level")
    if part["topic"] not in shared["topics"]:
        add("error", "unknown_topic", part["topic"])
    for g in part["expected_response"]["grammar_demands"]:
        if g["id"] not in tax["grammar_level"]:
            add("error", "unknown_grammar_id", g["id"])
    for c in part["classification"]["cognitive_processes"]:
        if c not in tax["cognitive_processes"]:
            add("error", "unknown_cognitive_process", c)
    subs = tax[sk]["subskills"]
    for s in [part["classification"]["primary_subskill"]] + part["classification"]["secondary_subskills"]:
        if s not in subs:
            add("error", "unknown_subskill", s)
    if part["classification"]["primary_subskill"] in part["classification"]["secondary_subskills"]:
        add("error", "primary_in_secondary", part["classification"]["primary_subskill"])
    bad = walk_keys({k: v for k, v in part.items() if k != "provenance"})
    if bad:
        add("error", "answer_key_present", ", ".join(bad))
    # learner-facing language complexity ----------------------------------------------------
    asl, lw = readability(learner_text(part))
    if asl > cfg["prompt_max_avg_sentence"]:
        add("warn", "prompt_sentences_too_long", f"avg {asl:.1f} words > {cfg['prompt_max_avg_sentence']} for {lv}")
    if lw > cfg["prompt_max_long_word_ratio"]:
        add("warn", "prompt_vocabulary_too_hard", f"long-word ratio {lw:.2f} > {cfg['prompt_max_long_word_ratio']} for {lv}")
    if len(words(t["prompt"])) < 5:
        add("error", "prompt_too_short", t["prompt"])
    if not re.search(r"[.?!]$", t["prompt"].strip()):
        add("warn", "prompt_no_end_punctuation", t["prompt"])
    if SENSITIVE.search(json.dumps({k: part[k] for k in ("task", "context", "title")})):
        add("warn", "sensitive_content_keyword", "check cultural suitability for the target audience")
    lo, hi = cfg["abstractness"]
    ab = part["provenance"]["raw_spec"]["abs"]
    if not lo <= ab <= hi:
        add("warn", "abstractness_out_of_range", f"abstractness {ab} outside {lo}-{hi} for {lv}")
    # grammar / cognition demand vs level -----------------------------------------------------
    gl = [LV[g["level"]] for g in part["expected_response"]["grammar_demands"]]
    if gl:
        if max(gl) > LV[lv] + 1:
            add("error", "grammar_demand_above_level", f"max grammar level {LEVELS[max(gl)]} > {lv}+1")
        elif max(gl) > LV[lv]:
            add("warn", "grammar_demand_adjacent_above", f"max grammar level {LEVELS[max(gl)]} > target {lv} (adjacent-level demand; document)")
        if max(gl) < LV[lv] - 0 and lv != "A1":
            add("warn" if max(gl) == LV[lv] - 1 else "error", "grammar_demand_below_level", f"max grammar level {LEVELS[max(gl)]} < target {lv}")
    cl = [LV[tax["cognitive_processes"][c]["level"]] for c in part["classification"]["cognitive_processes"] if c in tax["cognitive_processes"]]
    if cl and max(cl) < LV[lv] - 1:
        add("error", "cognitive_demand_below_level", f"max cognitive level {LEVELS[max(cl)]} < target {lv}-1")
    elif cl and max(cl) < LV[lv]:
        add("warn", "cognitive_demand_below_target", f"max cognitive level {LEVELS[max(cl)]} < target {lv}")
    if cl and max(cl) > LV[lv] + 1:
        add("warn", "cognitive_demand_above_level", f"max cognitive level {LEVELS[max(cl)]} > {lv}+1")
    # objectives -------------------------------------------------------------------------------
    for o in part["classification"]["learning_objectives"]:
        if o["measurable_verb"] not in OBJ_VERBS:
            add("warn", "objective_verb_not_measurable", o["text"])
    # blueprint relevance --------------------------------------------------------------------
    crit = {c["id"]: c for c in part["evaluation_blueprint"]["criteria"]}
    total = sum(c["weight"] for c in crit.values())
    if abs(total - 1) > 0.01:
        add("error", "criterion_weights_not_normalised", f"sum {total:.3f}")
    if sk == "writing":
        if lv in ("A1", "A2") and "W_ORG" in crit:
            add("error", "criterion_not_appropriate_for_level", "essay-organisation criterion at A1/A2")
        argumentative = part["task_category"] in ("argumentative_essay", "discussion_two_views", "advantages_disadvantages", "problem_solution")
        if argumentative and LV[lv] >= LV["B2"] and "W_ORG" not in crit:
            add("error", "criterion_missing", "argumentative B2+ task without organisation/development criterion")
        if LV[lv] >= LV["C1"] and crit.get("W_LR", {"weight": 0})["weight"] + crit.get("W_GRA", {"weight": 0})["weight"] > 0.45:
            add("warn", "advanced_task_overweights_accuracy", "lexis+grammar weight > 0.45 at C1/C2")
        if lv == "A1" and crit.get("W_TA", {"weight": 0})["weight"] < 0.25:
            add("warn", "a1_task_fulfilment_underweighted", "task fulfilment < 0.25 at A1")
        if part["task_category"] in ("email_formal", "register_transformation", "report", "proposal", "address_speech") and "W_REG" not in crit:
            add("error", "criterion_missing", "register-sensitive task without register criterion")
    else:
        if "S_PRON" in crit:
            add("error", "pronunciation_scored_in_text_mvp", "S_PRON must not be a scored criterion in the text-only MVP")
        if not any(n["id"] == "S_PRON" for n in part["evaluation_blueprint"]["not_assessed_by_design"]):
            add("error", "pronunciation_not_marked_unavailable", "S_PRON must be listed under not_assessed_by_design")
        if "text_mvp_limitations" not in part["evaluation_blueprint"]:
            add("error", "text_mvp_limitations_missing", "")
        fc = crit.get("S_FC")
        if fc and fc["assessable_in_current_modality"] != "partial":
            add("error", "fluency_wrongly_marked_assessable", "S_FC is partial in text")
    for c in crit.values():
        for k in ("successful_performance", "weak_performance", "expected_evidence", "evaluation_limitations"):
            if len(c[k].strip()) < 10 or "Not applicable" in c[k]:
                add("error", "criterion_incomplete", f"{c['id']}.{k}")
        if not c["related_subskills"]:
            add("error", "criterion_incomplete", f"{c['id']}.related_subskills")
    if not part["evaluation_blueprint"]["not_penalised"]:
        add("error", "not_penalised_missing", "")
    # skill-specific task checks -----------------------------------------------------------
    if sk == "writing":
        w = t["word_count"]
        mn, smin, smax, mx = w["minimum"], w["suggested_min"], w["suggested_max"], w["maximum"]
        if not mn <= smin <= smax <= mx:
            add("error", "word_count_not_ordered", f"{mn}/{smin}/{smax}/{mx}")
        for name, val, rng in (("minimum", mn, cfg["words"]["min"]), ("suggested_min", smin, cfg["words"]["suggested_min"]), ("suggested_max", smax, cfg["words"]["suggested_max"]), ("maximum", mx, cfg["words"]["max"])):
            if not rng[0] <= val <= rng[1]:
                add("error", "word_count_out_of_range", f"{name}={val} not in {rng} for {lv}")
        if not cfg["minutes"][0] <= t["suggested_minutes"] <= cfg["minutes"][1]:
            add("error", "time_out_of_range", f"{t['suggested_minutes']} min not in {cfg['minutes']} for {lv}")
        pace = ((smin + smax) / 2) / t["suggested_minutes"]
        if not WRITE_PACE[0] <= pace <= WRITE_PACE[1]:
            add("error", "implausible_writing_pace", f"{pace:.1f} words/min")
        npts = len(t["required_points"])
        if not cfg["points"][0] <= npts <= cfg["points"][1]:
            add("warn", "required_point_count", f"{npts} points outside {cfg['points']} for {lv}")
        if sum(len(words(x)) for x in t["instructions"]) > 80 and lv in ("A1", "A2"):
            add("warn", "instructions_long_for_level", "")
        if "stimulus" in t and len(t["stimulus"]["content"].split()) < 25:
            add("warn", "stimulus_short", "")
    else:
        sd = t["suggested_speaking_seconds"]
        if not cfg["seconds"][0] <= sd <= cfg["seconds"][1]:
            add("error", "speaking_time_out_of_range", f"{sd}s not in {cfg['seconds']} for {lv}")
        if not cfg["prep"][0] <= t["preparation_seconds"] <= cfg["prep"][1]:
            add("error", "prep_time_out_of_range", f"{t['preparation_seconds']}s not in {cfg['prep']} for {lv}")
        tw = t["typed_response_words"]
        if not tw["minimum"] <= tw["suggested_min"] <= tw["suggested_max"]:
            add("error", "typed_words_not_ordered", str(tw))
        if not cfg["typed_words"]["min"][0] <= tw["minimum"] <= cfg["typed_words"]["min"][1]:
            add("error", "typed_min_out_of_range", f"{tw['minimum']} not in {cfg['typed_words']['min']} for {lv}")
        if not cfg["typed_words"]["suggested_max"][0] <= tw["suggested_max"] <= cfg["typed_words"]["suggested_max"][1]:
            add("error", "typed_max_out_of_range", f"{tw['suggested_max']} not in {cfg['typed_words']['suggested_max']} for {lv}")
        spoken = sd / 60 * tax["speaking"]["pace_wpm_spoken"][lv]
        if not 0.25 * spoken <= tw["suggested_min"] <= 1.1 * spoken or tw["suggested_max"] > 1.35 * spoken:
            add("warn", "typed_length_vs_duration", f"typed {tw['suggested_min']}-{tw['suggested_max']} vs ~{spoken:.0f} spoken words for {sd}s")
        fmt = t["format"]
        if fmt in ("long_turn", "long_turn_discussion"):
            cue = t.get("cue_card", {}).get("points", [])
            if not 3 <= len(cue) <= 5:
                add("error", "cue_card_points", f"{len(cue)} cue points")
            if not t["preparation_seconds"] and lv not in ("A1",):
                add("warn", "long_turn_without_preparation", "")
        if fmt in ("discussion", "long_turn_discussion", "situational_response", "familiar_topics") and not t["follow_up_questions"]:
            add("error", "follow_ups_missing", fmt)
        for q in [t["main_question"]] + t["follow_up_questions"]:
            invites = INVITES.search(q)
            if fmt != "situational_response" and LV[lv] >= LV["B1"] and YESNO_START.match(q.strip()) and not WH_WORD.search(q) and not invites:
                add("warn", "yes_no_question_at_B1_plus", q)
        if fmt == "discussion" and LV[lv] >= LV["B1"] and len(t["follow_up_questions"]) < 2:
            add("warn", "discussion_needs_follow_ups", "")
        if re.search(r"(?i)\bpronunciation\b", " ".join(t["instructions"])) and "not assessed" not in " ".join(t["instructions"]):
            add("warn", "pronunciation_claim_in_instructions", "")
    return f


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def toks(text):
    stop = {"the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "your", "you", "about", "is", "are", "with", "what", "how", "do", "it", "that", "this", "for", "at", "by", "as"}
    return [w.lower() for w in words(text) if w.lower() not in stop and len(w) > 2]


def duplicate_scan(parts):
    """Pairwise near-duplicate scan across the whole skill; returns candidate rows."""
    rows = []
    for a, b in itertools.combinations(parts, 2):
        if a["skill"] != b["skill"]:
            continue
        def core(p):
            t = p["task"]
            if p["skill"] == "writing":
                return toks(t["prompt"] + " " + " ".join(t["required_points"]))
            return toks(t["main_question"] + " " + " ".join(t["follow_up_questions"]) + " " + " ".join(t.get("cue_card", {}).get("points", [])))
        def head(p):
            t = p["task"]
            return toks(t["prompt"]) if p["skill"] == "writing" else toks(t["main_question"])
        j_prompt = jaccard(head(a), head(b))
        j_task = jaccard(core(a), core(b))
        j_obj = jaccard(toks(" ".join(o["text"] for o in a["classification"]["learning_objectives"])), toks(" ".join(o["text"] for o in b["classification"]["learning_objectives"])))
        same_shape = (a.get("task_category") or a.get("task_format")) == (b.get("task_category") or b.get("task_format")) and a["topic"] == b["topic"]
        j_out = jaccard(toks(" ".join(a["expected_response"]["examples"][0]["outline"])), toks(" ".join(b["expected_response"]["examples"][0]["outline"])))
        reasons = []
        if j_prompt >= 0.6:
            reasons.append(f"prompt_jaccard={j_prompt:.2f}")
        elif j_prompt >= 0.4:
            reasons.append(f"prompt_similar={j_prompt:.2f}")
        if j_task >= 0.5:
            reasons.append(f"task_content_jaccard={j_task:.2f}")
        if a["title"].strip().lower() == b["title"].strip().lower():
            reasons.append("identical_title")
        if same_shape and a["target_cefr"] == b["target_cefr"]:
            reasons.append("same_format_topic_level")
        if j_obj >= 0.8 and a["target_cefr"] == b["target_cefr"] and a["classification"]["primary_subskill"] == b["classification"]["primary_subskill"]:
            reasons.append(f"same_objective_demand={j_obj:.2f}")
        if j_out >= 0.6:
            reasons.append(f"outline_jaccard={j_out:.2f}")
        if reasons:
            severe = j_prompt >= 0.6 or j_task >= 0.5 or "identical_title" in reasons or "same_format_topic_level" in reasons
            rows.append({"skill": a["skill"], "part_a": a["id"], "part_b": b["id"], "level_a": a["target_cefr"], "level_b": b["target_cefr"],
                         "prompt_jaccard": round(j_prompt, 2), "task_content_jaccard": round(j_task, 2), "objective_jaccard": round(j_obj, 2), "outline_jaccard": round(j_out, 2),
                         "reasons": "; ".join(reasons), "severity": "duplicate" if severe else "near_duplicate_review"})
    return rows


def bank_checks(parts, tax):
    """Whole-bank structural and diversity checks. Returns (errors, warnings)."""
    errs, warns = [], []
    for sk in ("writing", "speaking"):
        ps = [p for p in parts if p["skill"] == sk]
        if len(ps) != 70:
            errs.append(f"{sk}: expected 70 parts, found {len(ps)}")
        by_bank = defaultdict(list)
        for p in ps:
            by_bank["placement" if p["assessment"]["type"] == "placement" else p["assessment"]["level"]].append(p)
        for b in ["placement"] + LEVELS:
            if len(by_bank.get(b, [])) != 10:
                errs.append(f"{sk}/{b}: expected 10 parts, found {len(by_bank.get(b, []))}")
        pl = Counter(p["target_cefr"] for p in by_bank.get("placement", []))
        want = tax["placement_design"]["level_counts"]
        if dict(pl) != want:
            errs.append(f"{sk}/placement: level coverage {dict(pl)} != designed {want}")
        for b in LEVELS:
            bad = [p["id"] for p in by_bank.get(b, []) if p["target_cefr"] != b]
            if bad:
                errs.append(f"{sk}/{b}: parts not targeting {b}: {bad}")
        for b, group in by_bank.items():
            topics = Counter(p["topic"] for p in group)
            over = {k: v for k, v in topics.items() if v > 2}
            if over:
                errs.append(f"{sk}/{b}: topic repeated more than twice {over}")
            key = "task_category" if sk == "writing" else "task_format"
            kinds = Counter(p[key] for p in group)
            if max(kinds.values()) > (4 if sk == "writing" else 5):
                warns.append(f"{sk}/{b}: task type dominates ({dict(kinds)})")
            if len(kinds) < (3 if sk == "writing" else 3):
                warns.append(f"{sk}/{b}: fewer than 3 task types ({dict(kinds)})")
        alltopics = Counter(p["topic"] for p in ps)
        if max(alltopics.values()) > 8:
            warns.append(f"{sk}: topic '{alltopics.most_common(1)[0][0]}' used {alltopics.most_common(1)[0][1]} times")
    ids = Counter(p["id"] for p in parts)
    uu = Counter(p["uuid"] for p in parts)
    errs += [f"duplicate id {k}" for k, v in ids.items() if v > 1]
    errs += [f"duplicate uuid {k}" for k, v in uu.items() if v > 1]
    return errs, warns


def load_bank(bank):
    parts, paths = [], {}
    for p in sorted(Path(bank).glob("**/part.json")):
        d = load_json(p)
        if d.get("skill") not in ("writing", "speaking"):
            continue
        parts.append(d)
        paths[d.get("id", str(p))] = p
    return parts, paths


def validate_all(parts, paths=None):
    tax, shared = taxonomy(), shared_taxonomy()
    per_part, bank_errs = {}, []
    for p in parts:
        se = schema_errors(p)
        findings = [] if se else part_findings(p, tax, shared)
        est = cefr_mod.estimate(p["provenance"]["raw_spec"], p["skill"]) if not se else None
        cefr_f = []
        if est:
            gap = abs(LV[est["recommended_cefr"]] - LV[p["target_cefr"]])
            if est["recommended_cefr"] != p["difficulty"]["recommended_cefr"]:
                cefr_f.append(("error", "stored_cefr_estimate_stale", "difficulty block does not match a fresh estimate"))
            if gap >= 1:
                cefr_f.append(("warn", "cefr_estimate_differs_from_target", f"heuristic {est['recommended_cefr']} vs target {p['target_cefr']} (gap {gap})"))
            if est["cefr_confidence"] == "low":
                cefr_f.append(("warn", "cefr_confidence_low", f"component spread sd={est['component_spread_sd']}"))
        per_part[p["id"]] = {"schema_errors": se, "findings": findings + cefr_f}
    be, bw = bank_checks(parts, tax)
    dups = duplicate_scan(parts)
    for d in dups:
        if d["severity"] == "duplicate":
            be.append(f"duplicate/near-duplicate parts {d['part_a']} & {d['part_b']}: {d['reasons']}")
    return {"parts": per_part, "bank_errors": be, "bank_warnings": bw, "duplicates": dups}


def summarise(res):
    s_err = sum(1 for r in res["parts"].values() if r["schema_errors"] or any(f[0] == "error" for f in r["findings"]))
    return {"parts_checked": len(res["parts"]), "parts_with_errors": s_err, "bank_errors": res["bank_errors"], "bank_warnings": res["bank_warnings"],
            "duplicate_candidates": len(res["duplicates"])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default=str(BANK))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    parts, paths = load_bank(a.bank)
    res = validate_all(parts, paths)
    for pid, r in res["parts"].items():
        for e in r["schema_errors"]:
            print(f"[ERROR] {pid} schema: {e}")
        for sev, code, detail in r["findings"]:
            print(f"[{sev.upper()}] {pid} {code}: {detail}")
    for e in res["bank_errors"]:
        print(f"[ERROR] bank: {e}")
    for w in res["bank_warnings"]:
        print(f"[WARN] bank: {w}")
    s = summarise(res)
    print(json.dumps(s, indent=1) if a.json else f"checked {s['parts_checked']} parts; parts with errors: {s['parts_with_errors']}; bank errors: {len(s['bank_errors'])}; bank warnings: {len(s['bank_warnings'])}")
    return 1 if s["parts_with_errors"] or s["bank_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
