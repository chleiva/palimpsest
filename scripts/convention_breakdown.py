"""Accuracy with and without the two output conventions (empty-set gold; established-false yes/no),
against the FROZEN gold. Usage: python scripts/convention_breakdown.py -> data/s3/_convention_breakdown.json"""
import collections, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.scorer import score
from eval.metrics import bootstrap_mean
from revise_stream.model import load_stream
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = {}
for setting, outd in (("setting3", "s3"), ("setting2_100", "s2")):
    per = collections.defaultdict(lambda: collections.defaultdict(list)); cnt = collections.Counter()
    for d in sorted(glob.glob(os.path.join(ROOT, "data", outd, "s*_*"))):
        sid = os.path.basename(d)
        try:
            A = json.load(open(os.path.join(d, "answers.json")))
        except Exception:
            continue
        fro = os.path.join(d, "frozen.json")
        gold = json.load(open(fro))["gold"] if os.path.exists(fro) else json.load(open(os.path.join(ROOT, "data", setting, sid + ".gold.json")))
        s = load_stream(os.path.join(ROOT, "data", setting, sid + ".json")); qs = {q.id: q for q in s.queries}
        for sysn in ("palimpsest", "log_llm_adjudicator", "temporal_db", "log_rule_adjudicator", "log_llm_adjudicator_c2"):
            if sysn not in A:
                continue
            ans = A[sysn]; w, w_ne, r, r_ne = [], [], [], []
            for qid, g in gold.items():
                q = qs[qid]
                if "pre" in q.tags or q.slot == "reported":
                    continue
                empty = g["status"] == "established" and g["assertion"] == []; hF = q.slot == "yesno" and g["assertion"] is False
                sc = score(ans.get(qid) or {"query_id": qid}, g, s, q)["exact"]
                if g.get("warranted") and q.slot == "downstream":
                    w.append(sc); (w_ne.append(sc) if not empty else None)
                    if sysn == "palimpsest": cnt["warr_total"] += 1; cnt["warr_empty"] += empty
                if g["status"] == "established":
                    r.append(sc); (r_ne.append(sc) if not (empty or hF) else None)
                    if sysn == "palimpsest": cnt["est_total"] += 1; cnt["est_empty"] += empty; cnt["holds_false"] += hF
            for k, v in (("warr", w), ("warr_ne", w_ne), ("res", r), ("res_ne", r_ne)):
                if v: per[sysn][k].append(sum(v) / len(v))
    out[setting] = dict(cnt)
    for sysn in per:
        out[setting][sysn] = {k: (round(bootstrap_mean(v, n_boot=3000)[0], 3), len(v)) for k, v in per[sysn].items()}
json.dump(out, open(os.path.join(ROOT, "data", "s3", "_convention_breakdown.json"), "w"), indent=1)
for k, v in out.items(): print(k, v)
