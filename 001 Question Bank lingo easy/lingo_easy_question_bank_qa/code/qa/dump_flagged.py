import json,sys
from .common import *
def main(bank):
    rows=[json.loads(l) for l in open(REPORTS/"semantic_review.jsonl",encoding="utf-8")]
    ents={e["part"]["id"]:e["part"] for e in load_parts()}
    for r in rows:
        if r["bank"]!=bank or r["semantic_status"]=="pass": continue
        p=ents[r["part_id"]]
        it=next(i for _,i in items_of(p) if i["id"]==r["question_id"])
        print(f'{it["id"]} [{it["level"]["cefr"]}] {it["prompt"]}')
        for o in it["options"]: print("   "+("*" if o["id"]==it["answer"] else " ")+o["id"]+". "+o["text"])
        ev=it.get("evidence")
        print("   ev:",ev["quote"] if ev else None,"| flags:",",".join(f["code"].replace("extreme_wording_in_distractor","EXTREME").replace("length_cue_correct_option_longest","LEN") for f in r["findings"] if f["severity"]=="major"))
if __name__=="__main__": main(sys.argv[1])
