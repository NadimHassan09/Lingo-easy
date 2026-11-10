#!/usr/bin/env python3
"""
Lingo Easy - part validator / stamper / bank reporter.

Usage
  python scripts/validate_part.py question_bank/placement_test/listening/LI001/part.json
  python scripts/validate_part.py question_bank/placement_test/listening/LI001/part.json --stamp
  python scripts/validate_part.py --bank question_bank            # validate everything + coverage report
  python scripts/validate_part.py examples/.../part.json --mini   # relaxed counts for the tiny examples

Exit code 0 = no errors, 1 = errors found.
No third-party dependencies (jsonschema is used only if installed).
"""
import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
EXTREME_RE = re.compile(r"\b(completely|totally|always|never|entirely|absolutely|useless|a waste of)\b", re.I)
TFNG = ["True", "False", "Not Given"]
YNNG = ["Yes", "No", "Not Given"]


# ----------------------------------------------------------------------------- helpers
def lv_is_b2_plus(it):
    return (it.get("level") or {}).get("cefr") in ("B2", "C1", "C2")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(text):
    """Lowercase, unify quotes, drop punctuation, collapse whitespace (for evidence matching)."""
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_count(text):
    return len(re.findall(r"\b[\w']+\b", text))


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


# ----------------------------------------------------------------------------- core validation
def validate_part(part, cfg, tax, mini=False, folder=None):
    r = Report()
    derived = {}

    def need(obj, keys, where):
        ok = True
        for k in keys:
            if k not in obj:
                r.err(f"{where}: missing '{k}'")
                ok = False
        return ok

    top_ok = need(part, ["schema_version", "id", "skill", "part_type", "title", "topic",
                         "profile", "text_cefr", "question_groups", "meta"], "part")
    if not top_ok:
        return r, derived

    skill, pid = part["skill"], part["id"]
    if skill not in cfg["skills"]:
        r.err(f"skill must be one of {list(cfg['skills'])}")
        return r, derived
    scfg = cfg["skills"][skill]
    vcfg = cfg["validation"]

    # ---- identity / folder
    if not re.fullmatch(rf"{scfg['id_prefix']}\d{{3,4}}", pid):
        r.err(f"id '{pid}' must look like {scfg['id_prefix']}001")
    if folder is not None and folder != pid:
        r.err(f"folder name '{folder}' must equal part id '{pid}'")
    if part["part_type"] not in scfg["part_types"]:
        r.err(f"part_type '{part['part_type']}' not in {list(scfg['part_types'])}")
    if part["topic"] not in tax["topics"]:
        r.err(f"topic '{part['topic']}' not in taxonomy.topics")
    if part["text_cefr"] not in CEFR_ORDER:
        r.err("text_cefr invalid")

    profile = part["profile"]
    pcfg = cfg["profiles"].get(profile)
    if not pcfg:
        r.err(f"profile must be one of {list(cfg['profiles'])}")
        return r, derived
    if part["text_cefr"] not in pcfg["text_cefr_allowed"]:
        r.err(f"text_cefr {part['text_cefr']} not allowed for profile {profile}: {pcfg['text_cefr_allowed']}")

    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    if "uuid" in part and not uuid_re.match(str(part["uuid"])):
        r.err("uuid is not a valid lowercase uuid")
    meta = part["meta"]
    if meta.get("status") not in tax["part_statuses"]:
        r.err(f"meta.status must be one of {tax['part_statuses']}")
    if "assets" in part and part["assets"]:
        r.warn("assets present but asset handling is not implemented yet")

    # ---- skill specific text block
    if skill == "listening":
        text_units = validate_listening_block(part, scfg, pcfg, tax, r, mini, pid)
    else:
        text_units = validate_reading_block(part, scfg, pcfg, r, mini)
    full_text = " ".join(t[1] for t in text_units)
    wc = word_count(full_text)
    derived["word_count"] = wc
    lo, hi = pcfg["text_words"][skill]
    if not (lo <= wc <= hi):
        (r.warn if mini else r.err)(f"word count {wc} outside {lo}-{hi} for profile {profile}")

    # ---- groups & items
    groups = part["question_groups"]
    glo, ghi = scfg["question_groups_per_part"]
    if not (glo <= len(groups) <= ghi):
        (r.warn if mini else r.err)(f"{len(groups)} question groups; expected {glo}-{ghi}")

    items = []
    allowed_pres = tax["presentations"][skill]
    for g in groups:
        if not need(g, ["id", "presentation", "instruction", "items"], f"group {g.get('id', '?')}"):
            continue
        if g["presentation"] not in allowed_pres:
            r.err(f"group {g['id']}: presentation '{g['presentation']}' not in {allowed_pres}")
        for it in g["items"]:
            items.append((g, it))

    expected_n = 4 if mini else scfg["items_per_part"]
    if len(items) != expected_n:
        r.err(f"{len(items)} items; expected exactly {expected_n}")

    bands, cefrs, answers = [], [], []
    last_pos = (-1, -1)
    for idx, (g, it) in enumerate(items, start=1):
        where = f"item #{idx}"
        if not need(it, ["id", "number", "prompt", "options", "answer", "level", "skill_tag",
                         "language_focus", "evidence", "explanation"], where):
            continue
        if it["number"] != idx:
            r.err(f"{where}: number is {it['number']}, expected {idx} (continuous across groups)")
        if it["id"] != f"{pid}-Q{idx:02d}":
            r.err(f"{where}: id must be {pid}-Q{idx:02d}")
        if not it["prompt"].strip():
            r.err(f"{where}: empty prompt")

        # options / answer
        opts = it["options"]
        texts = [o.get("text", "") for o in opts]
        ids = [o.get("id") for o in opts]
        if ids != ["A", "B", "C", "D"][:len(opts)]:
            r.err(f"{where}: option ids must be A,B,C(,D) in order")
        if not (vcfg["min_distractor_options"] <= len(opts) <= vcfg["max_options"]):
            r.err(f"{where}: needs {vcfg['min_distractor_options']}-{vcfg['max_options']} options")
        if len({norm(t) for t in texts}) != len(texts):
            r.err(f"{where}: duplicate option texts")
        if any(re.search(r"\b(all|none) of the above\b|\bboth [a-d] and [a-d]\b", t, re.I) for t in texts):
            r.err(f"{where}: 'all/none of the above' style options are not allowed")
        if it["answer"] not in ids:
            r.err(f"{where}: answer '{it['answer']}' is not one of the option ids")
        if lv_is_b2_plus(it) and g["presentation"] not in ("true_false_not_given", "yes_no_not_given"):
            wrong = [t for o, t in zip(ids, texts) if o != it["answer"] and EXTREME_RE.search(t)]
            if wrong:
                r.warn(f"{where}: B2+ distractor(s) with extreme wording {wrong}: rewrite as plausible options")
        if g["presentation"] == "true_false_not_given" and texts != TFNG:
            r.err(f"{where}: TFNG options must be exactly {TFNG}")
        if g["presentation"] == "yes_no_not_given" and texts != YNNG:
            r.err(f"{where}: YNNG options must be exactly {YNNG}")
        answers.append(it["answer"])

        # level
        lv = it["level"]
        if lv.get("cefr") not in CEFR_ORDER:
            r.err(f"{where}: level.cefr invalid")
        else:
            lo_b, hi_b = cfg["cefr_to_band"][lv["cefr"]]
            b = lv.get("band")
            if not isinstance(b, (int, float)):
                r.err(f"{where}: level.band must be a number")
            else:
                if abs(b * 2 - round(b * 2)) > 1e-9:
                    r.err(f"{where}: band {b} must be a multiple of {cfg['band_step']}")
                if not (lo_b <= b <= hi_b):
                    r.err(f"{where}: band {b} outside {lv['cefr']} range {lo_b}-{hi_b}")
                bands.append(float(b))
                cefrs.append(lv["cefr"])

        # tags
        if it["skill_tag"] not in tax["skill_tags"][skill]:
            r.err(f"{where}: skill_tag '{it['skill_tag']}' not in taxonomy.skill_tags.{skill}")
        lf = it["language_focus"]
        t = lf.get("type")
        if t == "grammar":
            if lf.get("rule") not in tax["grammar_rules"]:
                r.err(f"{where}: grammar rule '{lf.get('rule')}' not in taxonomy.grammar_rules")
        elif t == "vocabulary":
            if lf.get("lexical_type") not in tax["lexical_types"]:
                r.err(f"{where}: lexical_type '{lf.get('lexical_type')}' not in taxonomy.lexical_types")
            if not str(lf.get("target", "")).strip():
                r.err(f"{where}: vocabulary focus needs a 'target' word/phrase")
        elif t != "none":
            r.err(f"{where}: language_focus.type must be grammar|vocabulary|none")

        if len(str(it["explanation"]).strip()) < vcfg["min_explanation_chars"]:
            r.err(f"{where}: explanation too short")

        # evidence
        ev = it["evidence"]
        not_given = it["answer"] in ids and texts[ids.index(it["answer"])] == "Not Given"
        if ev is None:
            if not not_given:
                r.err(f"{where}: evidence is required unless the correct answer is 'Not Given'")
        else:
            pos = locate_evidence(ev, text_units, skill)
            if pos is None:
                r.err(f"{where}: evidence quote not found verbatim in the {'transcript' if skill == 'listening' else 'passage'}")
            elif skill == "listening":
                if pos < last_pos:
                    r.err(f"{where}: evidence appears BEFORE the previous item's evidence (listening items must follow audio order)")
                last_pos = max(last_pos, pos)

    # ---- distribution checks
    n = len(items)
    if cefrs:
        share = Counter(cefrs)
        derived["level_counts"] = {k: share.get(k, 0) for k in CEFR_ORDER}
        derived["mean_band"] = round(sum(bands) / len(bands), 2)
        lo_m, hi_m = pcfg["mean_band_range"]
        if not (lo_m <= derived["mean_band"] <= hi_m):
            r.err(f"mean band {derived['mean_band']} outside {lo_m}-{hi_m} for profile {profile}")
        missing = [lv for lv in pcfg["required_levels"] if share.get(lv, 0) == 0]
        if missing:
            r.err(f"profile {profile} must include items at levels {missing}")
        top = max(share.values()) / len(cefrs)
        max_share = pcfg.get("max_level_share", vcfg["max_level_share"])
        if top > max_share + 1e-9:
            r.err(f"one CEFR level holds {top:.0%} of items (max {max_share:.0%})")
    if answers:
        ac = Counter(answers)
        derived["answer_counts"] = dict(sorted(ac.items()))
        if not mini and n >= 8:
            if max(ac.values()) / n > vcfg["max_same_answer_share"] + 1e-9:
                r.err(f"answer letter imbalance: {dict(ac)}")
            run = best = 1
            for a, b2 in zip(answers, answers[1:]):
                run = run + 1 if a == b2 else 1
                best = max(best, run)
            if best > vcfg["max_answer_run"]:
                r.err(f"same answer letter {best} times in a row (max {vcfg['max_answer_run']})")

    # ---- content hash
    derived["content_hash"] = content_hash(part)
    return r, derived


def _strip_uuid(obj):
    if isinstance(obj, dict):
        return {k: _strip_uuid(v) for k, v in obj.items() if k != "uuid"}
    if isinstance(obj, list):
        return [_strip_uuid(v) for v in obj]
    return obj


def content_hash(part):
    """Hash of the educational content only (no derived/meta/uuid), so stamping never changes it."""
    payload = _strip_uuid({k: v for k, v in part.items() if k not in ("derived", "meta")})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def assign_uuids(part):
    """Stable ids: random uuid4 for the part once, deterministic uuid5 per item. Never overwrites existing ones."""
    if "uuid" not in part:
        part["uuid"] = str(uuid.uuid4())
    ns = uuid.UUID(part["uuid"])
    for g in part["question_groups"]:
        for it in g["items"]:
            it.setdefault("uuid", str(uuid.uuid5(ns, it["id"])))


def validate_listening_block(part, scfg, pcfg, tax, r, mini, pid):
    if "audio" not in part:
        r.err("listening part needs 'audio'")
        return []
    a = part["audio"]
    if not all(k in a for k in ("file", "speakers", "transcript")):
        r.err("audio needs file, speakers, transcript")
        return []
    if not re.fullmatch(rf"{pid.lower()}_[a-z0-9_]+\.mp3", a["file"]):
        r.err(f"audio.file must match {pid.lower()}_<slug>.mp3 (lowercase, underscores)")
    sp_ids = [s.get("id") for s in a["speakers"]]
    if len(set(sp_ids)) != len(sp_ids):
        r.err("duplicate speaker ids")
    for s in a["speakers"]:
        if s.get("gender") not in tax["speaker_genders"]:
            r.err(f"speaker {s.get('id')}: gender must be {tax['speaker_genders']}")
        if s.get("accent") not in tax["speaker_accents"]:
            r.err(f"speaker {s.get('id')}: accent must be one of {tax['speaker_accents']}")
    lo, hi = scfg["part_types"].get(part["part_type"], {}).get("speakers", [1, 4])
    if not (lo <= len(sp_ids) <= hi):
        r.err(f"part_type {part['part_type']} needs {lo}-{hi} speakers, found {len(sp_ids)}")
    units = []
    for i, turn in enumerate(a["transcript"]):
        if turn.get("speaker") not in sp_ids:
            r.err(f"transcript turn {i}: unknown speaker '{turn.get('speaker')}'")
        text = turn.get("text", "")
        if re.search(r"[\[\]*<>#]", text):
            r.err(f"transcript turn {i}: remove markup/stage directions ([ ] * < > #) - text goes straight to TTS")
        units.append((str(i), text))
    return units


def validate_reading_block(part, scfg, pcfg, r, mini):
    if "passage" not in part:
        r.err("reading part needs 'passage'")
        return []
    ps = part["passage"].get("paragraphs", [])
    labels = [p.get("label") for p in ps]
    expected = [chr(ord("A") + i) for i in range(len(ps))]
    if labels != expected:
        r.err(f"paragraph labels must run {expected}, found {labels}")
    return [(p.get("label", "?"), p.get("text", "")) for p in ps]


def locate_evidence(ev, units, skill):
    """Return a sortable position tuple (unit_index, char_offset) or None if quote not found."""
    quote = norm(ev.get("quote", ""))
    if len(quote.split()) < 3:
        return None
    if skill == "reading":
        label = ev.get("paragraph")
        for i, (lab, text) in enumerate(units):
            if lab == label:
                off = norm(text).find(quote)
                return (i, off) if off >= 0 else None
        return None
    for i, (_, text) in enumerate(units):
        off = norm(text).find(quote)
        if off >= 0:
            return (i, off)
    return None


# ----------------------------------------------------------------------------- CLI
def run_single(path, cfg, tax, args):
    path = Path(path)
    part = load_json(path)
    folder = path.parent.name if path.name == "part.json" and not args.mini else None
    r, derived = validate_part(part, cfg, tax, mini=args.mini, folder=folder)
    tag = "OK " if not r.errors else "FAIL"
    print(f"[{tag}] {path}  ({part.get('id', '?')}, {part.get('profile', '?')})")
    for e in r.errors:
        print(f"   ERROR   {e}")
    for w in r.warnings:
        print(f"   warn    {w}")
    if derived.get("level_counts"):
        print(f"   levels={derived['level_counts']} mean_band={derived.get('mean_band')} "
              f"answers={derived.get('answer_counts')} words={derived.get('word_count')}")
    if args.stamp and not r.errors:
        assign_uuids(part)
        part["derived"] = derived
        if part["meta"].get("status") == "draft":
            part["meta"]["status"] = "validated"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(part, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("   stamped: uuids + derived fields written, status=validated")
    elif args.stamp:
        print("   not stamped (fix errors first)")
    return len(r.errors)


def run_bank(bank_dir, cfg, tax, args, quiet=False):
    bank = Path(bank_dir)
    total_err = 0
    seen_ids, seen_titles, seen_audio = {}, {}, {}
    stats = {sk: {"parts": 0, "profile": Counter(), "levels": Counter(), "topics": Counter(),
                  "types": Counter(), "grammar": Counter(), "vocab": Counter()} for sk in cfg["skills"]}
    for sk in cfg["skills"]:
        for p in sorted((bank / sk).glob("*/part.json")):
            part = load_json(p)
            r, d = validate_part(part, cfg, tax, mini=args.mini, folder=p.parent.name)
            if r.errors:
                total_err += len(r.errors)
                print(f"[FAIL] {p}")
                for e in r.errors:
                    print(f"   ERROR {e}")
            pid = part.get("id")
            for store, key, label in ((seen_ids, pid, "id"),
                                      (seen_titles, str(part.get("title", "")).strip().lower(), "title"),
                                      (seen_audio, (part.get("audio") or {}).get("file"), "audio file")):
                if key:
                    if key in store:
                        total_err += 1
                        print(f"[FAIL] duplicate {label} '{key}': {store[key]} and {p}")
                    store[key] = str(p)
            s = stats[sk]
            s["parts"] += 1
            s["profile"][part.get("profile")] += 1
            s["topics"][part.get("topic")] += 1
            s["types"][part.get("part_type")] += 1
            for k, v in (d.get("level_counts") or {}).items():
                s["levels"][k] += v
            for g in part.get("question_groups", []):
                for it in g.get("items", []):
                    lf = it.get("language_focus", {})
                    if lf.get("type") == "grammar":
                        s["grammar"][lf.get("rule")] += 1
                    elif lf.get("type") == "vocabulary":
                        s["vocab"][lf.get("lexical_type")] += 1
    if quiet:
        counts = {sk: stats[sk]["parts"] for sk in stats}
        levels = Counter()
        for s in stats.values():
            levels.update(s["levels"])
        print(f"  parts: {counts}  item levels: {dict(levels)}")
        print(f"  {total_err} error(s)")
        return total_err
    tgt = cfg["bank_targets"]
    print("\n=== BANK REPORT ===")
    for sk, s in stats.items():
        print(f"\n{sk.upper()}: {s['parts']}/{tgt['parts_per_skill']} parts")
        for prof, share in tgt["profile_share"].items():
            want = round(tgt["parts_per_skill"] * share)
            print(f"  profile {prof:<13} {s['profile'].get(prof, 0):>3} / {want}")
        print("  item levels:", {k: s["levels"].get(k, 0) for k in CEFR_ORDER})
        print("  part types :", dict(s["types"]))
        print("  topics     :", dict(s["topics"].most_common()))
        print("  grammar    :", dict(s["grammar"].most_common(8)), "...")
        print("  vocab types:", dict(s["vocab"]))
    print(f"\n{total_err} error(s)")
    return total_err


def run_productive(root):
    """Writing and Speaking parts live beside Reading/Listening; they are validated by the productive package."""
    sys.path.insert(0, str(ROOT))
    try:
        from productive import validate as pv
    except ImportError:
        return 0
    parts, paths = pv.load_bank(root)
    if not parts:
        return 0
    res = pv.validate_all(parts, paths)
    s = pv.summarise(res)
    print(f"--- writing/speaking parts: {s['parts_checked']} checked, {s['parts_with_errors']} with errors, {len(s['bank_errors'])} bank-level errors, {len(s['bank_warnings'])} warnings ---")
    for pid, r in res["parts"].items():
        for e in r["schema_errors"]:
            print(f"[FAIL] {pid} schema: {e}")
        for sev, code, detail in r["findings"]:
            if sev == "error":
                print(f"[FAIL] {pid} {code}: {detail}")
    for e in res["bank_errors"]:
        print(f"[FAIL] bank: {e}")
    return s["parts_with_errors"] + len(s["bank_errors"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="path to a part.json")
    ap.add_argument("--bank", help="validate every part under this question_bank directory")
    ap.add_argument("--stamp", action="store_true", help="write derived fields + status=validated when clean")
    ap.add_argument("--mini", action="store_true", help="relaxed mode for the tiny 4-item examples")
    args = ap.parse_args()
    cfg = load_json(ROOT / "config" / "blueprint.json")
    tax = load_json(ROOT / "config" / "taxonomy.json")
    if args.bank:
        root = Path(args.bank)
        placement = root / "placement_test"
        errs = run_bank(placement if placement.is_dir() else root, cfg, tax, args)  # flat layout still accepted for examples/
        for lvl_dir in sorted((root / "assessment_test").glob("*")):
            if lvl_dir.is_dir():
                print(f"--- assessment bank {lvl_dir.name} ---")
                errs += run_bank(lvl_dir, cfg, tax, args, quiet=True)
        errs += run_productive(root)
        sys.exit(1 if errs else 0)
    if not args.path:
        ap.error("give a part.json path or --bank DIR")
    sys.exit(1 if run_single(args.path, cfg, tax, args) else 0)


if __name__ == "__main__":
    main()
