"""
Build a DEMO bank by cloning the tiny example parts, so you can try assembler + server + frontend
before the real bank exists.  The clones are NOT real content (same questions, different ids).

  python scripts/make_demo_bank.py            -> demo_bank/
  LINGO_BANK_DIR=demo_bank python -m server.dev_server
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ["foundation", "intermediate", "advanced", "intermediate", "foundation", "advanced"]
LISTENING_TYPES = ["social_conversation", "social_monologue", "academic_discussion", "academic_lecture"]
READING_TYPES = ["descriptive", "discursive", "argumentative"]
TOPICS = ["travel", "education", "health", "technology", "environment", "housing"]


def build_demo_bank(dest, n_each=6, src=ROOT / "examples" / "question_bank"):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for skill, prefix, types in (("listening", "LI", LISTENING_TYPES), ("reading", "RE", READING_TYPES)):
        with open(Path(src) / skill / f"{prefix}001" / "part.json", encoding="utf-8") as f:
            raw = f.read()
        for i in range(n_each):
            new_id = f"{prefix}{101 + i}"
            part = json.loads(raw.replace(f"{prefix}001", new_id).replace(f"{prefix.lower()}001", new_id.lower()))
            part.pop("uuid", None)
            for g in part["question_groups"]:
                for it in g["items"]:
                    it.pop("uuid", None)
            part["title"] = f"{part['title']} (demo {i + 1})"
            part["profile"] = PROFILES[i % len(PROFILES)]
            part["part_type"] = types[i % len(types)]
            part["topic"] = TOPICS[i % len(TOPICS)]
            part["meta"] = {**part["meta"], "status": "validated", "notes": "DEMO CLONE - not real content"}
            out = dest / skill / new_id
            out.mkdir(parents=True)
            with open(out / "part.json", "w", encoding="utf-8") as f:
                json.dump(part, f, ensure_ascii=False, indent=2)
    return dest
