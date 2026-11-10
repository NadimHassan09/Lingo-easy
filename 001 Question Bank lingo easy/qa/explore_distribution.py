"""Exploratory: distribution of the CURRENT (pre-blueprint) assembler, used to choose feasible blueprint bounds."""
import json
import sys
from collections import Counter, defaultdict

from assembler.assemble import assemble
from assembler.blueprint import CEFR, exam_metrics, load_meta
from assembler.bank import load_bank
from .common import BANK, PLACEMENT, assessment_dir

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
meta = load_meta()
types = [("placement", None, PLACEMENT)] + [(f"assessment_{lv}", lv, assessment_dir(lv)) for lv in CEFR]
for name, lv, d in types:
    bank, _ = load_bank(d, ["validated", "reviewed", "approved"])
    byid = {p["id"]: p for s in bank.values() for p in s}
    mins, maxs = {c: 999 for c in CEFR}, {c: 0 for c in CEFR}
    sub_distinct = defaultdict(list)
    topic_max = []
    for seed in range(N):
        _, st = assemble(d, seed=seed, level=lv)
        parts = [byid[p["part_id"]] for p in st["parts"]]
        m = exam_metrics(parts, meta)
        for c in CEFR:
            mins[c] = min(mins[c], m["by_level"][c])
            maxs[c] = max(maxs[c], m["by_level"][c])
        for sk in ("listening", "reading"):
            sub_distinct[sk].append(len([s for s in m["by_subskill"].get(sk, {}) if s != "unknown"]))
        topic_max.append(max(m["topics"].values()))
    print(name, "levels min", mins, "max", maxs, "subskills L", min(sub_distinct["listening"]), max(sub_distinct["listening"]),
          "R", min(sub_distinct["reading"]), max(sub_distinct["reading"]), "topic max", Counter(topic_max))
