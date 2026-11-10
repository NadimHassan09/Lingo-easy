"""Stage 1 and 2: inventory, integrity findings, duplicate candidates, asset audit.

Usage: python -m qa.stage1_inventory_integrity [--out DIR]
Independent re-implementation of the key integrity rules (plus a cross-check with scripts/validate_part.py).
"""
import argparse
import itertools
import json
import re
import sys
from collections import Counter, defaultdict

from .common import *  # noqa: F401,F403

sys.path.insert(0, str(ROOT / "scripts"))
import validate_part as V  # noqa: E402

CFG = json.loads((ROOT / "config" / "blueprint.json").read_text(encoding="utf-8"))
TAX = json.loads((ROOT / "config" / "taxonomy.json").read_text(encoding="utf-8"))
TF = ["True", "False", "Not Given"]
YN = ["Yes", "No", "Not Given"]
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def question_records(entries):
    recs = []
    for e in entries:
        p = e["part"]
        for g, it in items_of(p):
            correct = next((o["text"] for o in it["options"] if o["id"] == it["answer"]), None)
            recs.append({
                "question_id": it["id"], "uuid": it.get("uuid"), "bank": e["bank"], "source_file": e["rel"],
                "assessment_type": "placement" if e["bank"] == "placement" else "level_" + e["bank"].split("_")[1],
                "modality": p["skill"], "source_passage_or_transcript_id": p["id"], "part_id": p["id"], "part_uuid": p.get("uuid"),
                "group_id": g["id"], "question_type": g["presentation"], "profile": p["profile"],
                "original_cefr": it["level"]["cefr"], "original_band": it["level"]["band"], "text_cefr": p["text_cefr"],
                "skill_tag": it.get("skill_tag"), "language_focus": it.get("language_focus"), "topic": p.get("topic"),
                "part_type": p.get("part_type"), "prompt": it["prompt"], "options": [o["text"] for o in it["options"]],
                "answer_id": it["answer"], "answer_text": correct, "evidence": it.get("evidence"), "explanation": it.get("explanation"),
                "audio_file": (p.get("audio") or {}).get("file"), "part_status": (p.get("meta") or {}).get("status"),
            })
    return recs


def check_part(e, add):
    p, rel = e["part"], e["rel"]
    pid = p.get("id", "?")
    for k in ("schema_version", "id", "skill", "part_type", "title", "topic", "profile", "text_cefr", "question_groups", "meta", "uuid"):
        if k not in p:
            add(pid, rel, "hard", "missing_part_field", f"missing '{k}'", "add the field")
    if p["id"] != e["path"].parent.name:
        add(pid, rel, "hard", "folder_id_mismatch", f"folder {e['path'].parent.name} != id {p['id']}", "rename folder or id")
    if not UUID_RE.match(str(p.get("uuid", ""))):
        add(pid, rel, "hard", "bad_part_uuid", str(p.get("uuid")), "regenerate with --stamp")
    if p["topic"] not in TAX["topics"]:
        add(pid, rel, "hard", "topic_not_in_taxonomy", p["topic"], "map to taxonomy")
    if p["profile"] not in CFG["profiles"]:
        add(pid, rel, "hard", "unknown_profile", p["profile"], "fix profile")
    units = source_units(p)
    if not units or not all(t.strip() for _, t in units):
        add(pid, rel, "hard", "empty_source", "empty passage/transcript", "add source text")
    if p["skill"] == "listening":
        sp = {s["id"] for s in p["audio"]["speakers"]}
        for t in p["audio"]["transcript"]:
            if t["speaker"] not in sp:
                add(pid, rel, "hard", "unknown_speaker", t["speaker"], "fix speaker reference")
        lo, hi = CFG["skills"]["listening"]["part_types"][p["part_type"]]["speakers"]
        if not lo <= len(sp) <= hi:
            add(pid, rel, "hard", "speaker_count_vs_part_type", f"{len(sp)} speakers for {p['part_type']}", "fix part_type or speakers")
        for s in p["audio"]["speakers"]:
            if s.get("accent") not in TAX["speaker_accents"] or s.get("gender") not in TAX["speaker_genders"]:
                add(pid, rel, "hard", "speaker_metadata", str(s), "use taxonomy values")
        audio = (e["path"].parent / p["audio"]["file"])
        if not audio.exists():
            add(pid, rel, "warning", "audio_file_missing", p["audio"]["file"] + " (audio generation is a later TTS step)", "generate audio before release; transcript mode is in use")
    # derived stats recomputed from authoritative data
    d = p.get("derived") or {}
    items = [it for _, it in items_of(p)]
    wc = V.word_count(" ".join(t for _, t in units))
    lc = Counter(it["level"]["cefr"] for it in items)
    exp_lc = {k: lc.get(k, 0) for k in CEFR}
    if d.get("word_count") != wc:
        add(pid, rel, "hard", "derived_word_count", f"stored {d.get('word_count')} vs recomputed {wc}", "re-stamp")
    if d.get("level_counts") != exp_lc:
        add(pid, rel, "hard", "derived_level_counts", f"stored {d.get('level_counts')} vs {exp_lc}", "re-stamp")
    mb = round(sum(i["level"]["band"] for i in items) / len(items), 2)
    if d.get("mean_band") != mb:
        add(pid, rel, "hard", "derived_mean_band", f"stored {d.get('mean_band')} vs {mb}", "re-stamp")
    ac = dict(sorted(Counter(i["answer"] for i in items).items()))
    if d.get("answer_counts") != ac:
        add(pid, rel, "hard", "derived_answer_counts", f"stored {d.get('answer_counts')} vs {ac}", "re-stamp")
    if d.get("content_hash") != V.content_hash(p):
        add(pid, rel, "hard", "derived_content_hash", "stored hash != recomputed", "re-stamp after any edit")
    exp_n = CFG["skills"][p["skill"]]["items_per_part"]
    if len(items) != exp_n:
        add(pid, rel, "hard", "item_count", f"{len(items)} items, blueprint says {exp_n}", "fix item count")
    cross = V.validate_part(p, CFG, TAX, folder=e["path"].parent.name)[0]
    for er in cross.errors:
        add(pid, rel, "hard", "existing_validator_error", er, "see scripts/validate_part.py rule")
    for w in cross.warnings:
        add(pid, rel, "warning", "existing_validator_warning", w, "review wording")


def check_item(e, g, it, n, add):
    p, rel, qid = e["part"], e["rel"], it.get("id", "?")
    for k in ("id", "number", "prompt", "options", "answer", "level", "skill_tag", "language_focus", "evidence", "explanation", "uuid"):
        if k not in it:
            add(qid, rel, "hard", "missing_item_field", f"missing '{k}'", "add the field")
            return
    if not UUID_RE.match(str(it["uuid"])):
        add(qid, rel, "hard", "bad_item_uuid", str(it["uuid"]), "stamp")
    if it["number"] != n or it["id"] != f"{p['id']}-Q{n:02d}":
        add(qid, rel, "hard", "numbering", f"number {it['number']} id {it['id']} expected {n}", "renumber")
    ids = [o["id"] for o in it["options"]]
    texts = [o["text"] for o in it["options"]]
    if ids != list("ABCD")[:len(ids)]:
        add(qid, rel, "hard", "option_ids", str(ids), "use A,B,C(,D)")
    if not 3 <= len(ids) <= 4:
        add(qid, rel, "hard", "option_count", str(len(ids)), "3 or 4 options")
    if len({norm(t) for t in texts}) != len(texts):
        add(qid, rel, "hard", "duplicate_options", str(texts), "make options distinct")
    if it["answer"] not in ids:
        add(qid, rel, "hard", "answer_not_in_options", it["answer"], "fix key")
    if sum(1 for o in it["options"] if o["id"] == it["answer"]) != 1:
        add(qid, rel, "hard", "not_exactly_one_correct", "", "fix key")
    if g["presentation"] == "true_false_not_given" and texts != TF:
        add(qid, rel, "hard", "tfng_options", str(texts), "use True/False/Not Given")
    if g["presentation"] == "yes_no_not_given" and texts != YN:
        add(qid, rel, "hard", "ynng_options", str(texts), "use Yes/No/Not Given")
    lv = it["level"]
    lo, hi = CFG["cefr_to_band"][lv["cefr"]]
    if not lo <= lv["band"] <= hi:
        add(qid, rel, "hard", "band_outside_cefr_range", f"{lv}", "fix band")
    if it["skill_tag"] not in TAX["skill_tags"][p["skill"]]:
        add(qid, rel, "hard", "skill_tag_not_in_taxonomy", it["skill_tag"], "map tag")
    ev = it["evidence"]
    answer_text = next((o["text"] for o in it["options"] if o["id"] == it["answer"]), "")
    is_ng = answer_text == "Not Given"
    if ev is None:
        if not is_ng:
            add(qid, rel, "hard", "evidence_missing", "non-NG item without evidence", "add evidence")
    else:
        if is_ng:
            add(qid, rel, "warning", "ng_with_evidence", "Not Given item carries evidence", "remove evidence")
        q = norm(ev["quote"])
        if len(q.split()) < 3:
            add(qid, rel, "warning", "short_evidence_quote", ev["quote"], "use 3+ words")
        if p["skill"] == "reading":
            para = dict(source_units(p)).get(ev.get("paragraph"))
            if para is None:
                add(qid, rel, "hard", "evidence_paragraph_missing", str(ev.get("paragraph")), "fix label")
            elif q not in norm(para):
                add(qid, rel, "hard", "evidence_not_in_cited_paragraph", ev["quote"], "fix quote or paragraph")
        else:
            if q not in norm(source_text(p)):
                add(qid, rel, "hard", "evidence_not_in_transcript", ev["quote"], "fix quote")
        # explanation vs answer/evidence lexical agreement (cheap proxy, NOT semantic proof)
        et = set(toks(it["explanation"]))
        if not et & (set(toks(answer_text)) | set(toks(ev["quote"]))):
            add(qid, rel, "warning", "explanation_lexically_unrelated", it["explanation"], "check that explanation supports the key")
    if len(it["explanation"].strip()) < 15:
        add(qid, rel, "hard", "explanation_too_short", it["explanation"], "expand")
    lf = it["language_focus"]
    if lf.get("type") == "grammar" and lf.get("rule") not in TAX["grammar_rules"]:
        add(qid, rel, "hard", "bad_grammar_rule", str(lf), "taxonomy")
    if lf.get("type") == "vocabulary" and lf.get("lexical_type") not in TAX["lexical_types"]:
        add(qid, rel, "hard", "bad_lexical_type", str(lf), "taxonomy")


def duplicates(recs, entries):
    rows = []
    by_bank = defaultdict(list)
    for r in recs:
        by_bank[r["bank"]].append(r)
    sets = {r["question_id"]: set(toks(r["prompt"] + " " + (r["answer_text"] or ""))) for r in recs}
    for bank, rs in by_bank.items():
        for a, b in itertools.combinations(rs, 2):
            if a["part_id"] == b["part_id"]:
                continue
            sa, sb = sets[a["question_id"]], sets[b["question_id"]]
            if len(sa) < 3 or len(sb) < 3:
                continue
            j = len(sa & sb) / len(sa | sb)
            same_prompt = norm(a["prompt"]) == norm(b["prompt"])
            if j >= 0.75 or (same_prompt and j >= 0.5):
                rows.append({"kind": "item", "id_a": a["question_id"], "id_b": b["question_id"], "bank": bank, "similarity": round(j, 3),
                             "detail": "identical prompt" if same_prompt else "similar prompt+key", "severity": "warning" if j >= 0.9 else "info",
                             "recommended_action": "avoid placing both in one exam; consider rewording"})
    def sh(t):
        w = norm(t).split()
        return {" ".join(w[i:i + 5]) for i in range(len(w) - 4)}
    sh_cache = {e["part"]["id"]: sh(source_text(e["part"])) for e in entries}
    ids = list(sh_cache)
    for a, b in itertools.combinations(ids, 2):
        j = len(sh_cache[a] & sh_cache[b]) / max(1, len(sh_cache[a] | sh_cache[b]))
        if j >= 0.15:
            rows.append({"kind": "source", "id_a": a, "id_b": b, "bank": "all", "similarity": round(j, 3), "detail": "5-gram overlap of passages/transcripts",
                         "severity": "warning", "recommended_action": "review for reuse"})
    titles = defaultdict(list)
    for e in entries:
        titles[norm(e["part"]["title"])].append(e["part"]["id"])
    for t, v in titles.items():
        if len(v) > 1:
            rows.append({"kind": "title", "id_a": v[0], "id_b": v[1], "bank": "all", "similarity": 1.0, "detail": "duplicate title", "severity": "warning", "recommended_action": "rename"})
    return rows


def asset_audit(entries):
    rows = []
    for e in entries:
        p = e["part"]
        folder = e["path"].parent
        if p["skill"] == "listening":
            f = p["audio"]["file"]
            exists = (folder / f).exists()
            rows.append({"part_id": p["id"], "source_path": e["rel"], "asset_type": "audio", "reference": f, "exists": exists,
                         "transcript_words": len(source_text(p).split()), "transcript_turns": len(p["audio"]["transcript"]),
                         "severity": "info" if not exists else "ok",
                         "note": "audio not generated yet (TTS step pending)" if not exists else "present; transcript/audio match NOT verified (no ASR in this environment)",
                         "recommended_action": "generate audio with scripts/export_tts_scenario.py and verify by ASR/human" if not exists else "verify audio against transcript"})
            tts = folder / "tts-config.json"
            rows.append({"part_id": p["id"], "source_path": e["rel"], "asset_type": "tts_config", "reference": "tts-config.json", "exists": tts.exists(),
                         "transcript_words": "", "transcript_turns": "", "severity": "info", "note": "optional until TTS", "recommended_action": ""})
        else:
            rows.append({"part_id": p["id"], "source_path": e["rel"], "asset_type": "passage_inline", "reference": "passage.paragraphs", "exists": True,
                         "transcript_words": len(source_text(p).split()), "transcript_turns": len(p["passage"]["paragraphs"]), "severity": "ok",
                         "note": "inline text", "recommended_action": ""})
        if p.get("assets"):
            rows.append({"part_id": p["id"], "source_path": e["rel"], "asset_type": "assets_list", "reference": str(p["assets"]), "exists": "", "transcript_words": "",
                         "transcript_turns": "", "severity": "warning", "note": "assets[] present but not handled", "recommended_action": "implement or empty"})
    return rows


def run(out=None):
    out = out or REPORTS
    out.mkdir(parents=True, exist_ok=True)
    entries = load_parts()
    findings = []

    def add(rid, path, sev, check, evidence, action):
        findings.append({"record_id": rid, "source_path": path, "severity": sev, "check": check, "evidence": evidence, "recommended_action": action})

    # global uniqueness
    seen = defaultdict(list)
    for e in entries:
        p = e["part"]
        seen["part_id:" + p["id"]].append(e["rel"])
        seen["part_uuid:" + str(p.get("uuid"))].append(e["rel"])
        check_part(e, add)
        for n, (g, it) in enumerate(items_of(p), start=1):
            seen["item_id:" + it.get("id", "?")].append(e["rel"])
            seen["item_uuid:" + str(it.get("uuid"))].append(e["rel"])
            check_item(e, g, it, n, add)
    for k, v in seen.items():
        if len(v) > 1:
            add(k, ";".join(v), "hard", "duplicate_identifier", f"{k} appears {len(v)} times", "make identifiers unique")
    recs = question_records(entries)
    dups = duplicates(recs, entries)
    assets = asset_audit(entries)
    by_bank = Counter(r["bank"] for r in recs)
    inv = {
        "generated_by": "qa/stage1_inventory_integrity.py", "review_version": REVIEW_VERSION,
        "authoritative_files": "question_bank/**/part.json, config/blueprint.json, config/taxonomy.json, schemas/part.schema.json",
        "generated_artifacts": "exams/*.json (stored exams), derived{} blocks inside part.json (recomputed by --stamp), demo_bank/ (not present), lingo_easy_question_bank_qa/reports",
        "schema_versions": sorted({e["part"]["schema_version"] for e in entries}),
        "counts": {"parts": len(entries), "questions": len(recs), "questions_by_bank": dict(by_bank),
                   "parts_by_bank_and_skill": dict(Counter(f"{e['bank']}:{e['part']['skill']}" for e in entries)),
                   "questions_by_original_cefr": dict(Counter(r["original_cefr"] for r in recs)),
                   "questions_by_modality": dict(Counter(r["modality"] for r in recs)),
                   "questions_by_type": dict(Counter(r["question_type"] for r in recs))},
        "findings_summary": dict(Counter((f["severity"], f["check"]) for f in findings).most_common()) if False else
                            {f"{s}:{c}": n for (s, c), n in Counter((f["severity"], f["check"]) for f in findings).most_common()},
        "file_hashes_sha256": {e["rel"]: e["sha256"] for e in entries},
        "stored_exam_artifacts": sorted(p.name for p in (ROOT / "exams").glob("*.json"))[:5] + ["... (see exams/; all generated by smoke tests)"],
        "records": recs,
    }
    write_json(out / "inventory.json", inv)
    write_csv(out / "integrity_findings.csv", findings, ["record_id", "source_path", "severity", "check", "evidence", "recommended_action"])
    write_csv(out / "duplicate_candidates.csv", dups, ["kind", "id_a", "id_b", "bank", "similarity", "detail", "severity", "recommended_action"])
    write_csv(out / "asset_reference_audit.csv", assets, ["part_id", "source_path", "asset_type", "reference", "exists", "transcript_words", "transcript_turns", "severity", "note", "recommended_action"])
    hard = sum(1 for f in findings if f["severity"] == "hard")
    print(f"parts={len(entries)} questions={len(recs)} findings={len(findings)} hard={hard} dups={len(dups)} assets={len(assets)}")
    return {"parts": len(entries), "questions": len(recs), "findings": len(findings), "hard": hard, "duplicates": len(dups)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from pathlib import Path
    run(Path(a.out) if a.out else None)
