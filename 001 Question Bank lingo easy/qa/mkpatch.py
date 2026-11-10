import json,sys
def mk(name,P,reason="distractors rebalanced for length/form parity and plausibility (length_cue / extreme wording); key text and letter unchanged",conf="medium"):
    json.dump([{"id":i,"set":s,"reason":reason,"confidence":conf} for i,s in P],open(f"qa/patches/{name}.json","w",encoding="utf-8"),indent=1,ensure_ascii=False)
    print(name,len(P))
