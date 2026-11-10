#!/usr/bin/env python3
"""
Convert a Lingo Easy listening part.json into a TTS config for the source repo's
scripts/generate-tts/generate-tts.py (Gemini) or generate-tts-qwen.py.

  python scripts/export_tts_scenario.py question_bank/placement_test/listening/LI001/part.json
  -> question_bank/placement_test/listening/LI001/tts-config.json

Then, from the source repo:
  python scripts/generate-tts/generate-tts.py --config <that file> --output-dir question_bank/placement_test/listening/LI001

The resulting mp3 is named <scenario_id>.mp3 == audio.file of the part (scenario_id = file stem).
Nothing here calls any API. Refuses parts that have not passed validation (status draft).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_scenario(part, cfg):
    t = cfg["tts"]
    audio = part["audio"]
    preset = t["profile_to_preset"][part["profile"]]
    id_map, voice_pick, speakers = {}, {"female": 0, "male": 0}, []
    for i, sp in enumerate(audio["speakers"], start=1):
        sid = f"Speaker {i}"
        id_map[sp["id"]] = sid
        voices = t["voices"][sp["gender"]]
        voice = voices[voice_pick[sp["gender"]] % len(voices)]
        voice_pick[sp["gender"]] += 1
        role = sp.get("role", "speaker")
        speakers.append({
            "id": sid,
            "role": role,
            "voice_name": voice,
            "audio_profile": f"{sp['name']}, a {sp['gender']} {role} with a clear, natural voice.",
            "director_note_override": {"accent": t["accent_text"][sp["accent"]]},
        })
    return {
        "scenario_id": Path(audio["file"]).stem,
        "title": part["title"],
        "difficulty": preset,
        "scene": t["scene_by_part_type"][part["part_type"]],
        "sample_context": f"Placement-test recording, {part['profile']} level, CEFR {part['text_cefr']}. Clear and natural; never rushed.",
        "speakers": speakers,
        "transcript": [{"speaker": id_map[turn["speaker"]], "text": turn["text"]} for turn in audio["transcript"]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part")
    ap.add_argument("--out", help="output path (default: <part folder>/tts-config.json)")
    ap.add_argument("--allow-draft", action="store_true", help="export even if meta.status is draft")
    args = ap.parse_args()

    part = load(args.part)
    cfg = load(ROOT / "config" / "blueprint.json")
    if part.get("skill") != "listening":
        sys.exit("only listening parts have audio")
    if part["meta"]["status"] == "draft" and not args.allow_draft:
        sys.exit("part is still 'draft': run validate_part.py --stamp first (or pass --allow-draft)")
    base = load(ROOT / cfg["tts"]["base_config"])
    base.pop("scenario_template", None)
    base["scenario"] = build_scenario(part, cfg)
    out = Path(args.out) if args.out else Path(args.part).parent / "tts-config.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {out}  (scenario_id={base['scenario']['scenario_id']}, preset={base['scenario']['difficulty']})")


if __name__ == "__main__":
    main()
