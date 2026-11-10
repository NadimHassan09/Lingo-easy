"""Shared helpers for the Writing/Speaking generators (stdlib only)."""
import csv
import hashlib
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "productive"
BANK = ROOT / "question_bank"
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
LV = {l: i for i, l in enumerate(LEVELS)}
UUID_NS = uuid.UUID("6f1c5e1a-9d3b-4a53-8f0e-5a7d1c2b9e10")
GENERATOR = "lingoeasy-productive-generator"
GENERATOR_VERSION = "1.1.0"
PART_VERSION = "1.1.0"
SCHEMA_VERSION = "1.0"
AUTHORING_MODEL = "claude-sonnet-5-5"


def band_reference(level):
    """Approximate IELTS-band equivalent of a CEFR level, from config/blueprint.json (cefr_to_band). Returns (band, [lo, hi])."""
    lo, hi = load_json(ROOT / "config" / "blueprint.json")["cefr_to_band"][level]
    mid = (lo + hi) / 2
    return int(mid * 2 + 0.5) / 2, [lo, hi]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def write_csv(path, rows, fields=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else ["note"])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def taxonomy():
    return load_json(PKG / "config" / "productive_taxonomy.json")


def shared_taxonomy():
    return load_json(ROOT / "config" / "taxonomy.json")


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def words(text):
    return WORD_RE.findall(text or "")


def sentences(text):
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]
    return parts or [text or ""]


def readability(text):
    """(average sentence length in words, share of words with >= 9 letters)."""
    ws = words(text)
    ss = sentences(text)
    if not ws:
        return 0.0, 0.0
    return len(ws) / len(ss), sum(1 for w in ws if len(w) >= 9) / len(ws)


def part_id(skill, bank, n):
    """WR001-WR010 / SP001-SP010 for placement; WR101.. (A1) .. WR6xx (C2) for level banks."""
    prefix = "WR" if skill == "writing" else "SP"
    base = 0 if bank == "placement" else (LV[bank] + 1) * 100
    return f"{prefix}{base + n:03d}"


def part_dir(root, skill, bank, pid):
    root = Path(root)
    if bank == "placement":
        return root / "placement_test" / skill / pid
    return root / "assessment_test" / bank / skill / pid
