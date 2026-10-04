"""Transition table for the "unsupported propagation" endpoint (reviewer P0-5) and the share of
convention-affected queries in the primary endpoint (reviewer P0-3), from cached answers only.

For every non-warranted event query (tagged retraction_consequence, gold unchanged between tau-1 and
tau) we tabulate, per system, the transition of the answer's correctness between the tau-1 companion
and the event query: correct->correct, correct->wrong, wrong->correct, wrong->wrong, where "correct"
is exact match against gold. The registered metric (answer changed while gold unchanged) is reported
alongside as "instability"; the harm measure is correct->wrong.

Primary-endpoint share: among warranted downstream queries, how many have empty-set gold or are
otherwise convention-affected, and the LLM adjudicator's accuracy with and without them.

Usage: python scripts/transitions.py SETTINGDIR OUTDIR  (e.g. data/setting2_100 data/s2) -> OUTDIR/_transitions.json
"""
import collections, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.model import load_stream
from eval.scorer import score, norm


def main(setting, outd):
    trans = collections.defaultdict(collections.Counter)
    prim = {"n": 0, "empty_gold": 0, "per_system_exact": collections.Counter(), "per_system_exact_nonempty": collections.Counter(), "n_nonempty": 0}
    for d in sorted(glob.glob(os.path.join(outd, "s*_*"))):
        sid = os.path.basename(d)
        try:
            A = json.load(open(os.path.join(d, "answers.json")))
        except Exception:
            continue
        fro = os.path.join(d, "frozen.json")        # the evaluation gold is the FROZEN (post-adjudication) gold, as in nl/pipeline.score
        gold = json.load(open(fro))["gold"] if os.path.exists(fro) else json.load(open(os.path.join(setting, sid + ".gold.json")))
        s = load_stream(os.path.join(setting, sid + ".json"))
        qs = {q.id: q for q in s.queries}
        pre = {(q.entity, q.attr, q.slot, q.tau): q.id for q in s.queries if "pre" in q.tags}
        for qid, q in qs.items():
            g = gold[qid]
            if "pre" in q.tags:
                continue
            if q.slot == "downstream" and g.get("warranted"):
                prim["n"] += 1
                empty = g["assertion"] == []
                prim["empty_gold"] += empty
                prim["n_nonempty"] += (not empty)
                for name, ans in A.items():
                    ok = score(ans.get(qid) or {"query_id": qid}, g, s, q)["exact"]
                    prim["per_system_exact"][name] += ok
                    if not empty:
                        prim["per_system_exact_nonempty"][name] += ok
            if "event" in q.tags and q.slot in ("downstream", "current") and not g.get("warranted"):
                pid = pre.get((q.entity, q.attr, q.slot, q.tau - 1))
                if not pid:
                    continue
                g0 = gold.get(pid)
                if g0 is None or (g0["status"], norm(g0["assertion"]), norm(g0["alternatives"])) != (g["status"], norm(g["assertion"]), norm(g["alternatives"])):
                    continue
                for name, ans in A.items():
                    a0, a1 = ans.get(pid), ans.get(qid)
                    if not a0 or not a1:
                        continue
                    c0 = score(a0, g0, s, qs[pid])["exact"]; c1 = score(a1, g, s, q)["exact"]
                    changed = (a0["status"], norm(a0.get("assertion")), norm(a0.get("alternatives"))) != (a1["status"], norm(a1.get("assertion")), norm(a1.get("alternatives")))
                    trans[name][("C" if c0 else "W") + "->" + ("C" if c1 else "W")] += 1
                    trans[name]["instability"] += int(changed)
                    trans[name]["n"] += 1
    out = {"transitions": {k: dict(v) for k, v in trans.items()},
           "primary": {"n": prim["n"], "empty_gold": prim["empty_gold"], "n_nonempty": prim["n_nonempty"],
                       "exact": {k: round(v / prim["n"], 4) for k, v in prim["per_system_exact"].items()},
                       "exact_nonempty": {k: round(v / max(1, prim["n_nonempty"]), 4) for k, v in prim["per_system_exact_nonempty"].items()}}}
    json.dump(out, open(os.path.join(outd, "_transitions.json"), "w"), indent=1)
    print(f"{'system':<24}{'n':>6} {'C->C':>7} {'C->W':>7} {'W->C':>7} {'W->W':>7} {'instab':>8}")
    for name, c in trans.items():
        n = c["n"]
        print(f"{name:<24}{n:>6} " + " ".join(f"{c[k]/n:>7.3f}" for k in ("C->C", "C->W", "W->C", "W->W")) + f" {c['instability']/n:>8.3f}")
    p = out["primary"]
    print(f"primary endpoint: {p['n']} warranted downstream queries, {p['empty_gold']} with empty-set gold")
    for k in p["exact"]:
        print(f"  {k:<24} exact {p['exact'][k]:.3f}  excluding empty-set gold {p['exact_nonempty'][k]:.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
