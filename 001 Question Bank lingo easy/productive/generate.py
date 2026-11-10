"""Writing and Speaking Part generator (deterministic assembly of authored task specs into evaluation-ready Part records).

Usage:
  python -m productive.generate --skill writing --bank placement --seed 20261030 --out productive_bank
  python -m productive.generate --skill both --bank all --seed 20261030 --out productive_bank
  python -m productive.generate --skill speaking --bank B2 --count 4 --seed 7 --dry-run

There is no runtime LLM call. The task specs in productive/specs/ were authored by an LLM (recorded in provenance) and reviewed only by
automated rules; this module turns each spec into a complete Part with a task-specific evaluation blueprint, diagnostics and provenance.
A future LLM generator can plug in through `load_specs(...)`: any provider only has to return spec dicts, which pass through the same validation.
"""
import argparse
import datetime
import json
import random
import sys
from pathlib import Path
import uuid

from . import cefr as cefr_mod
from . import criteria_text as ct
from .common import (PKG, band_reference, AUTHORING_MODEL, BANK, GENERATOR, GENERATOR_VERSION, LEVELS, LV, PART_VERSION, SCHEMA_VERSION, UUID_NS, canonical, part_dir,
                     part_id, sha, taxonomy, write_json)
from .specs.registry import POOLS

TEXT_MODALITY = {"current": "typed_text", "planned": ["audio"], "note": "Learners type their response in the current MVP."}

LEVEL_DEMAND = {
    "A1": "Short, concrete sentences about familiar personal topics; high-frequency vocabulary; present simple.",
    "A2": "Short connected texts on everyday topics; simple past and future; simple linkers (and, but, because, so).",
    "B1": "Connected paragraphs on familiar and some abstract topics; narration, opinion with reasons; range of linkers; basic complex sentences.",
    "B2": "Developed, structured discourse; argument with supporting detail; evaluation of options; complex sentences and a range of cohesive devices.",
    "C1": "Well-structured, detailed discourse on complex and abstract topics; qualified positions; flexible register; nominalisation and hedging.",
    "C2": "Precise, sophisticated and stylistically controlled discourse; subtle distinctions, synthesis of sources; full range of structures with consistent control.",
}
DISCOURSE = {
    "A1": "Isolated sentences or very short sequences.", "A2": "Short connected text, one paragraph at most.",
    "B1": "One to three paragraphs or a connected multi-sentence turn.", "B2": "Structured multi-paragraph text or an extended, organised turn.",
    "C1": "Fully organised extended discourse with explicit argument structure.", "C2": "Sophisticated extended discourse with layered argument and controlled flow.",
}
NOT_PENALISED_WRITING = {
    "A1": ["missing paragraphs or linking beyond 'and' and 'but'", "minor spelling slips that do not hide meaning", "absence of any structure above present simple"],
    "A2": ["absence of complex sentences or of conditionals", "minor spelling or punctuation slips that do not hide meaning", "informal vocabulary where the task is informal"],
    "B1": ["absence of advanced structures (inversion, mixed conditionals)", "occasional spelling slips", "a plain but accurate vocabulary"],
    "B2": ["absence of C1/C2 devices (cleft sentences, subjunctive)", "idiomatic language that is not required", "factual inaccuracy about the topic (content knowledge is not assessed)"],
    "C1": ["absence of C2 stylistic devices", "the writer's opinion itself (judge how it is argued, not which side is chosen)", "factual inaccuracy beyond the supplied source material"],
    "C2": ["the position taken (any defensible, well-argued position is valid)", "absence of specific rhetorical devices", "factual inaccuracy beyond the supplied source material"],
}
NOT_PENALISED_SPEAKING = {
    "A1": ["very short answers (this is the expected length at A1)", "unusual spelling or punctuation (text MVP)", "repetition of the question wording in the answer"],
    "A2": ["short answers to short questions", "spelling or punctuation errors (text MVP)", "absence of complex grammar"],
    "B1": ["spelling or punctuation errors (text MVP)", "informal spoken-style contractions", "absence of advanced structures"],
    "B2": ["spelling or punctuation errors (text MVP)", "factual inaccuracy about the topic", "absence of C1/C2 devices"],
    "C1": ["spelling or punctuation errors (text MVP)", "the position taken (judge how it is argued)", "absence of C2 stylistic devices"],
    "C2": ["spelling or punctuation errors (text MVP)", "the position taken (any defensible position is valid)", "absence of particular rhetorical devices"],
}
L1_TRANSFER = {
    "A1": ["missing 'be' in present sentences (Arabic nominal sentences)", "omission or addition of 'the'", "he/she confusion"],
    "A2": ["preposition calques (in/on/at)", "plural and countable-noun errors", "adjective placement after noun"],
    "B1": ["tense mixing in narration", "'the' with general nouns", "preposition calques"],
    "B2": ["article use with abstract nouns", "relative clause pronoun repetition ('the man who he ...')", "overuse of 'and' as a clause linker"],
}
FALSE_START_NOTE = "These are hypotheses about common patterns; they are NOT to be reported as a learner weakness from a single instance."
EVALUATOR_OUTPUT = ["criterion_scores (with CEFR-band estimate and target-level attainment per criterion)", "overall_evaluation", "strengths", "weaknesses",
                    "evidence_quotes (exact spans from the learner response)", "detected_errors (with diagnostic category ids)", "recommended_learning_objectives",
                    "suggested_improvements", "evaluation_confidence", "assessment_limitations"]
OBS_VS_INFERRED = ("An error is OBSERVED when an instance appears in the response. It may be recorded as an INFERRED weakness only under the policy in "
                   "diagnostics.policy (repeated instances, enough text, and not explained by task demands).")


def _concat(a, b):
    return (a.rstrip(". ") + ". " + b) if b else a


def _crit_entry(skill, cid, spec, weight, tax):
    lib = ct.WRITING if skill == "writing" else ct.SPEAKING
    c = lib[cid]
    lv = spec["lv"]
    success = c["success"][lv]
    weak = c["weak"][lv]
    evidence = c["evidence"]
    if cid == "W_TA":
        success = _concat(success, "Required points: " + "; ".join(spec["pts"]))
        evidence += " Check each required point: " + "; ".join(spec["pts"]) + "."
    if cid == "S_REL":
        qs = [spec["main"]] + spec["follow"] + spec["cue"]
        success = _concat(success, "Needs to respond to: " + " | ".join(qs))
        evidence += " Check each question or cue point in turn."
    if cid == "W_REG":
        success = _concat(success, f"Audience: {spec['aud']}. Register: {spec['reg']}")
    if cid == "W_LR" or cid == "S_LR":
        evidence += " Expected vocabulary demands: " + "; ".join(spec["vocab"]) + "."
    if cid in ("W_GRA", "S_GRA"):
        evidence += " Structures invited by the task: " + ", ".join(spec["gram"]) + "."
    subs = [spec["sub"]] + spec["sub2"]
    related = sorted(set(subs))
    entry = {
        "id": cid, "name": c["name"], "description": c["description"], "weight": round(weight, 3),
        "assessable_in_current_modality": c.get("text_assessable", "yes"), "scored_in_text_mvp": c.get("text_assessable", "yes") != "no",
        "successful_performance": success, "weak_performance": weak, "expected_evidence": evidence,
        "common_error_patterns": c["mistakes"][lv], "related_subskills": related, "evaluation_limitations": c["limits"],
        "diagnostic_categories": [d for d, v in tax["diagnostics"]["categories"].items() if cid in v["criteria"] and skill in v["skills"]],
    }
    if cid in ("W_GRA", "S_GRA", "W_LR", "S_LR") and lv in L1_TRANSFER:
        entry["l1_transfer_hypotheses"] = {"patterns": L1_TRANSFER[lv], "caution": FALSE_START_NOTE}
    return entry


def evaluation_blueprint(skill, spec, tax):
    cat = spec["cat"] if skill == "writing" else spec["fmt"]
    weights = tax[skill]["categories" if skill == "writing" else "formats"][cat]["weights"]
    weights = dict(weights)
    if skill == "writing" and spec["lv"] in ("A1", "A2") and "W_ORG" in weights:
        weights["W_TA"] = weights.get("W_TA", 0) + weights.pop("W_ORG")  # essay organisation is not a construct at A1/A2
    scored = {k: v for k, v in weights.items() if v > 0}
    total = sum(scored.values())
    criteria = [_crit_entry(skill, cid, spec, w / total, tax) for cid, w in scored.items()]
    zero = [k for k, v in weights.items() if v == 0]
    not_assessed = []
    lib = ct.WRITING if skill == "writing" else ct.SPEAKING
    for cid in zero:
        reason = lib[cid]["limits"] if skill == "speaking" else "Not required by this task type."
        not_assessed.append({"id": cid, "name": lib[cid]["name"], "reason": reason})
    if skill == "writing":
        for cid in lib:
            if cid not in weights:
                not_assessed.append({"id": cid, "name": lib[cid]["name"], "reason": "Not required by this task type at this level, so it must not be used to reduce the score."})
    required = (["Address every required point: " + "; ".join(spec["pts"])] if skill == "writing"
                else ["Respond to every question or cue point: " + " | ".join([spec["main"]] + spec["cue"] + spec["follow"])])
    required.append("Use language appropriate to: " + (spec["aud"] if skill == "writing" else spec["scen"]))
    optional = list(spec["opt"]) if skill == "writing" else ["extra detail, examples or personal anecdotes", "the cue-card points in any order"]
    scale = {"type": "per_criterion_cefr_estimate", "values": ["below_A1"] + LEVELS,
             "target_level_attainment": {"0": "no evidence of target-level control", "1": "partial: some target-level features, frequent breakdowns",
                                         "2": "mostly secure: target-level features present with some lapses", "3": "secure: consistent target-level control"},
             "note": "Uncalibrated evaluator scale. Do not convert to an IELTS band without separate calibration."}
    bp = {"blueprint_version": "1.0", "response_modality": "typed_text", "target_cefr": spec["lv"],
          "criteria": criteria, "not_assessed_by_design": not_assessed,
          "required_demonstrations": required, "optional_demonstrations": optional,
          "not_penalised": NOT_PENALISED_WRITING[spec["lv"]] if skill == "writing" else NOT_PENALISED_SPEAKING[spec["lv"]],
          "scale": scale, "evaluator_output_contract": EVALUATOR_OUTPUT,
          "multiple_valid_responses": True,
          "notes": "The illustrative outline in expected_response.examples is NOT an answer key. Accept any response that fulfils the task."}
    if skill == "speaking":
        bp["text_mvp_limitations"] = ["Pronunciation, intonation, stress and rhythm cannot be assessed from typed text: do not assign a pronunciation score.",
                                      "Fluency in the sense of speech rate, pauses and hesitation cannot be assessed; only organisation and coherence can.",
                                      "Do not state or imply that this evaluation is a complete assessment of speaking."]
    return bp


def diagnostics(skill, spec, bp, tax):
    cats = tax["diagnostics"]["categories"]
    applicable = {c["id"] for c in bp["criteria"] if c["scored_in_text_mvp"]}
    lv = LV[spec["lv"]]
    chosen = []
    for d, v in cats.items():
        if skill not in v["skills"]:
            continue
        if not (set(v["criteria"]) & applicable):
            continue
        if d == "D_HEDGING" and lv < LV["B2"]:
            continue
        if d in ("D_ARGUMENT", "D_SUPPORT", "D_COMPARISON") and lv < LV["B1"]:
            continue
        if d == "D_SPELLING" and skill == "speaking":
            continue
        if d == "D_L1_TRANSFER" and lv > LV["B2"]:
            continue
        if d == "D_GRAMMAR_RANGE" and lv < LV["A2"]:
            continue
        if d == "D_ORGANISATION" and lv < LV["B1"]:
            continue
        chosen.append(d)
    if skill == "speaking":
        chosen.append("D_TEXT_ONLY_LIMIT")
    return {"targets": sorted(set(chosen)), "policy": tax["diagnostics"]["policy"], "observed_vs_inferred": OBS_VS_INFERRED}


class SpecError(ValueError):
    """A task spec is incomplete or uses values outside the controlled vocabularies. Generation stops instead of guessing."""


COMMON_KEYS = ["k", "lv", "topic", "title", "scen", "prompt", "vocab", "gram", "sub", "sub2", "cog", "obj", "outline", "abs"]
SKILL_KEYS = {"writing": ["cat", "pts", "aud", "reg", "w", "mins", "struct", "opt"], "speaking": ["fmt", "main", "cue", "follow", "prep", "dur", "w"]}


def check_spec(skill, spec, tax):
    errs = [f"missing key '{k}'" for k in COMMON_KEYS + SKILL_KEYS[skill] if k not in spec]
    if errs:
        raise SpecError(f"{spec.get('k', '?')}: " + "; ".join(errs))
    if spec["lv"] not in LV:
        errs.append(f"unknown level {spec['lv']}")
    errs += [f"unknown grammar id {g}" for g in spec["gram"] if g not in tax["grammar_level"]]
    errs += [f"unknown cognitive process {c}" for c in spec["cog"] if c not in tax["cognitive_processes"]]
    errs += [f"unknown sub-skill {x}" for x in [spec["sub"]] + spec["sub2"] if x not in tax[skill]["subskills"]]
    kind = spec.get("cat" if skill == "writing" else "fmt")
    if kind not in tax[skill]["categories" if skill == "writing" else "formats"]:
        errs.append(f"unknown task type {kind}")
    if not 0 <= spec["abs"] <= 3:
        errs.append("abs must be 0-3")
    if errs:
        raise SpecError(f"{spec['k']}: " + "; ".join(errs))


def build_part(skill, bank, spec, pid, seed, generated_at):
    tax = taxonomy()
    check_spec(skill, spec, tax)
    lv = spec["lv"]
    placement = bank == "placement"
    est = cefr_mod.estimate(spec, skill)
    gap = abs(LV[est["recommended_cefr"]] - LV[lv])
    prefix = "W" if skill == "writing" else "S"
    bp = evaluation_blueprint(skill, spec, tax)
    gram = [{"id": g, "level": tax["grammar_level"][g], "extension": g in tax["grammar_extensions"]} for g in spec["gram"]]
    objectives = [{"id": f"LO.{prefix}.{spec['sub']}.{lv}.{i + 1}", "text": o, "measurable_verb": o.split()[0].strip(",;:").lower(),
                   "criteria": [c["id"] for c in bp["criteria"] if c["scored_in_text_mvp"]][:3]} for i, o in enumerate(spec["obj"])]
    classification = {"primary_subskill": spec["sub"], "secondary_subskills": spec["sub2"], "cognitive_processes": spec["cog"], "learning_objectives": objectives}
    difficulty = {
        "original_target_cefr": lv, "recommended_cefr": est["recommended_cefr"], "cefr_confidence": est["cefr_confidence"],
        "level_gap_steps": gap, "difficulty_index": round(est["composite_index"] / 5, 3),
        "language_demand": LEVEL_DEMAND[lv], "cognitive_demand": "; ".join(tax["cognitive_processes"][c]["label"] for c in spec["cog"]),
        "expected_performance": [(ct.WRITING if skill == "writing" else ct.SPEAKING)[c["id"]]["success"][lv] for c in bp["criteria"][:3]],
        "rationale": (f"Heuristic components (0=A1 .. 5=C2): {est['components']}; composite {est['composite_index']} -> {est['recommended_cefr']}. "
                      f"Original target {lv}. Computed from invited grammar, cognitive operations, expected length, abstractness and prompt language only."),
        "adjacent_level_demands": [g["id"] for g in gram if LV[g["level"]] > LV[lv]],
        "method": "heuristic_v1", "calibrated": False, "human_review_required": True,
        "review_priority": "P1" if gap >= 2 or est["cefr_confidence"] == "low" and gap >= 1 else ("P2" if gap == 1 else "P3"),
        "components": est["components"], "prompt_readability": est["prompt_readability"]}
    common = {
        "schema_version": SCHEMA_VERSION, "id": pid, "uuid": str(uuid.uuid5(UUID_NS, f"lingoeasy:{skill}:{pid}")), "version": PART_VERSION,
        "skill": skill, "assessment": {"type": "placement" if placement else "assessment", "level": None if placement else bank},
        "target_cefr": lv, "level": {"cefr": lv, "band": band_reference(lv)[0]},
        "ielts_reference": {"band_range": band_reference(lv)[1], "note": "Approximate band-equivalent from config/blueprint.json cefr_to_band; not an IELTS score and not calibrated."},
        "profile": "placement" if placement else f"level_{bank.lower()}", "topic": spec["topic"], "context": spec["scen"], "title": spec["title"],
        "part_type": spec["cat"] if skill == "writing" else spec["fmt"], "skill_tag": spec["sub"],
        "modality": dict(TEXT_MODALITY),
    }
    if skill == "writing":
        w = spec["w"]
        task = {"title": spec["title"], "scenario": spec["scen"], "prompt": spec["prompt"],
                "instructions": [f"Write about {w[1]}-{w[2]} words (at least {w[0]}).", f"You have about {spec['mins']} minutes.",
                                 "Make sure you cover all of the points listed." if spec["pts"] else "",
                                 f"You are writing for: {spec['aud']}. Style: {spec['reg']}."],
                "required_points": spec["pts"], "audience": spec["aud"], "register": spec["reg"], "response_type": spec["cat"],
                "word_count": {"minimum": w[0], "suggested_min": w[1], "suggested_max": w[2], "maximum": w[3]}, "suggested_minutes": spec["mins"]}
        task["instructions"] = [x for x in task["instructions"] if x]
        if spec.get("stim"):
            task["stimulus"] = {"type": "text", "content": spec["stim"], "note": "Provided to the learner with the prompt; the response must not invent additional data."}
        expected = {"content_points": spec["pts"], "required_elements": [f"Address: {p}" for p in spec["pts"]], "optional_elements": spec["opt"],
                    "organisation": spec["struct"], "vocabulary_demands": spec["vocab"], "grammar_demands": gram,
                    "discourse_complexity": DISCOURSE[lv], "linguistic_demand": LEVEL_DEMAND[lv], "cognitive_demand": difficulty["cognitive_demand"],
                    "examples": [{"label": "Illustrative outline only - not an answer key; many other responses are equally valid", "outline": spec["outline"]}]}
        part = dict(common, task_category=spec["cat"], task=task, expected_response=expected)
    else:
        task = {"title": spec["title"], "format": spec["fmt"], "scenario": spec["scen"], "prompt": spec["prompt"],
                "instructions": (["Read what the other person says. Then write what you would say in reply to each line.",
                                  "Use complete sentences, as you would in a real conversation.",
                                  "In this version your answer is typed. Pronunciation is not assessed."] if spec["fmt"] == "situational_response" else
                                 ["Type your answer the way you would say it, in complete sentences.",
                                  "Answer every question or point. Add reasons and examples when you can.",
                                  "In this version your answer is typed. Pronunciation is not assessed."]),
                "main_question": spec["main"], "follow_up_questions": spec["follow"],
                "preparation_seconds": spec["prep"], "suggested_speaking_seconds": spec["dur"],
                "typed_response_words": {"minimum": spec["w"][0], "suggested_min": spec["w"][1], "suggested_max": spec["w"][2]}}
        if spec["cue"]:
            task["cue_card"] = {"topic": spec["main"], "points": spec["cue"], "preparation_seconds": spec["prep"], "speaking_seconds": spec["dur"]}
        expected = {"content_points": spec["cue"] or [spec["main"]] + spec["follow"], "required_elements": [f"Respond to: {q}" for q in ([spec["main"]] + spec["follow"] + spec["cue"])],
                    "optional_elements": ["extra detail, examples or a personal anecdote"], "organisation": ["answer each question or cue point in turn, adding reasons and examples"],
                    "vocabulary_demands": spec["vocab"], "grammar_demands": gram, "discourse_complexity": DISCOURSE[lv], "linguistic_demand": LEVEL_DEMAND[lv],
                    "cognitive_demand": difficulty["cognitive_demand"],
                    "examples": [{"label": "Illustrative outline only - not an answer key; many other responses are equally valid", "outline": spec["outline"]}]}
        part = dict(common, task_format=spec["fmt"], task=task, expected_response=expected)
    part.update({"classification": classification, "difficulty": difficulty, "evaluation_blueprint": bp, "diagnostics": diagnostics(skill, spec, bp, tax)})
    part["qa"] = {"structural_validation": "not_run", "semantic_rule_review": "not_run", "llm_review": "not_performed", "human_review": "not_reviewed",
                  "findings": []}
    part["provenance"] = {
        "generator": GENERATOR, "generator_version": GENERATOR_VERSION, "assembly": "deterministic", "seed": seed, "generated_at": generated_at,
        "spec_source": f"productive/specs/{'writing' if skill == 'writing' else 'speaking'}_*.py ({spec['k']})", "spec_sha256": sha(spec),
        "authoring": {"method": "task specs authored by an LLM in an interactive session; assembled by code; no runtime model call", "provider": "Anthropic",
                      "model": AUTHORING_MODEL, "generation_parameters": "not applicable (interactive authoring)", "runtime_llm_calls": 0},
        "raw_spec": spec}
    part["meta"] = {"status": "draft", "source": "ai_generated", "generator": f"{GENERATOR}@{GENERATOR_VERSION}", "model": AUTHORING_MODEL,
                    "notes": "Status becomes 'validated' only after structural validation passes. 'reviewed' and 'approved' are reserved for humans."}
    part["derived"] = {"content_hash": sha({k: v for k, v in part.items() if k not in ("provenance", "qa", "meta", "derived")})}
    return part


def banks_for(skill, bank):
    avail = list(POOLS[skill])
    return avail if bank == "all" else [bank]


def select_specs(skill, bank, count, seed):
    pool = POOLS[skill][bank]
    if count is None or count >= len(pool):
        return list(pool)
    rng = random.Random(f"{skill}:{bank}:{seed}")
    order = list(pool)
    rng.shuffle(order)
    chosen, topics, cats = [], set(), {}
    key = "cat" if skill == "writing" else "fmt"
    for s in sorted(order, key=lambda s: (cats.get(s[key], 0), rng.random())):
        if len(chosen) == count:
            break
        if s["topic"] in topics:
            continue
        chosen.append(s)
        topics.add(s["topic"])
        cats[s[key]] = cats.get(s[key], 0) + 1
    for s in order:
        if len(chosen) == count:
            break
        if s not in chosen:
            chosen.append(s)
    return sorted(chosen, key=lambda s: pool.index(s))


def generate(skill, bank, count=None, seed=20261030, generated_at=None):
    generated_at = generated_at or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    specs = select_specs(skill, bank, count, seed)
    pool = POOLS[skill][bank]
    return [build_part(skill, bank, s, part_id(skill, bank, pool.index(s) + 1), seed, generated_at) for s in specs]


def next_free_id(skill, bank, root):
    taken = {p.name for p in part_dir(root, skill, bank, "x").parent.glob("*") if p.is_dir()}
    for n in range(1, 100):
        pid = part_id(skill, bank, n)
        if pid not in taken:
            return pid
    raise SpecError(f"no free id left in {skill}/{bank}")


def from_spec_file(a):
    """Generate, validate and write one part from a JSON spec (the route the SKILL.md files describe for new parts)."""
    from . import validate as V
    if a.skill == "both" or a.bank == "all":
        print("--spec-file needs a single --skill (writing|speaking) and a single --bank", file=sys.stderr)
        return 2
    spec = json.loads(open(a.spec_file, encoding="utf-8").read())
    root = a.out
    pid = a.id or next_free_id(a.skill, a.bank, root)
    try:
        part = build_part(a.skill, a.bank, spec, pid, a.seed, a.generated_at or datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    except SpecError as e:
        print(f"SPEC ERROR: {e}", file=sys.stderr)
        return 1
    se = V.schema_errors(part)
    findings = [] if se else V.part_findings(part, taxonomy(), V.shared_taxonomy())
    errs = se + [f"{c}: {d}" for s, c, d in findings if s == "error"]
    for s, c, d in findings:
        print(f"[{s.upper()}] {pid} {c}: {d}")
    for e in errs:
        print(f"[ERROR] {pid} {e}")
    part["qa"]["structural_validation"] = "fail" if errs else "pass"
    part["qa"]["semantic_rule_review"] = "flagged" if any(s == "warn" for s, _, _ in findings) else "pass"
    part["qa"]["findings"] = [{"severity": s, "detail": f"{c}: {d}"} for s, c, d in findings]
    part["meta"]["status"] = "draft" if errs else "validated"
    if errs and not a.dry_run:
        print("not written: fix the errors above (the part would stay draft)")
        return 1
    if not a.dry_run:
        write_json(part_dir(root, a.skill, a.bank, pid) / "part.json", part)
        write_json(Path(a.spec_archive) / f"{pid}.json", spec)
    print(f"{'would write' if a.dry_run else 'wrote'} {pid} ({a.skill}, {a.bank}); status {part['meta']['status']}; bank-level counts/duplicates are checked by python -m productive.build")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", choices=["writing", "speaking", "both"], default="both")
    ap.add_argument("--bank", default="all", help="placement | A1..C2 | all")
    ap.add_argument("--count", type=int, default=None, help="number of parts per bank (default: the full authored pool)")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--out", default=str(BANK))
    ap.add_argument("--generated-at", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--spec-file", help="build ONE new part from a spec JSON (needs --skill writing|speaking and --bank); writes, validates and stamps it")
    ap.add_argument("--id", help="part id for --spec-file (default: next free id in that bank)")
    ap.add_argument("--spec-archive", default=str(PKG / "specs" / "json"), help="where --spec-file keeps a copy of the spec (provenance)")
    a = ap.parse_args(argv)
    if a.spec_file:
        return from_spec_file(a)
    skills = ["writing", "speaking"] if a.skill == "both" else [a.skill]
    n = 0
    for sk in skills:
        for b in banks_for(sk, a.bank):
            if b not in POOLS[sk]:
                print(f"unknown bank {b}", file=sys.stderr)
                return 2
            for p in generate(sk, b, a.count, a.seed, a.generated_at):
                n += 1
                if not a.dry_run:
                    write_json(part_dir(a.out, sk, b, p["id"]) / "part.json", p)
    print(f"{'would generate' if a.dry_run else 'generated'} {n} parts (unvalidated draft; run python -m productive.build to validate and stamp)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
