"""Rule-coded error taxonomy of the claims-log LLM adjudicator (original protocol) over all primary
scored answers (non-companion, non-`reported`), against the FROZEN gold; and the share of empty-set
gold among primary-endpoint queries with the adjudicator's micro accuracy with/without them.
Usage: python scripts/llm_error_taxonomy.py data/setting2_100 data/s2 -> OUTDIR/_error_taxonomy_llm.json"""
import collections, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.scorer import score, norm
from revise_stream.model import load_stream


def main(setting, outd, sysname="log_llm_adjudicator"):
    tax = collections.Counter(); n = 0
    prim = {"n": 0, "empty": 0, "ok": 0, "ok_nonempty": 0}
    for d in sorted(glob.glob(os.path.join(outd, "s*_*"))):
        sid = os.path.basename(d)
        try:
            A = json.load(open(os.path.join(d, "answers.json")))
        except Exception:
            continue
        fro = os.path.join(d, "frozen.json")
        gold = json.load(open(fro))["gold"] if os.path.exists(fro) else json.load(open(os.path.join(setting, sid + ".gold.json")))
        s = load_stream(os.path.join(setting, sid + ".json")); qs = {q.id: q for q in s.queries}
        ans = A[sysname]
        for qid, g in gold.items():
            q = qs[qid]
            if q.slot == "reported" or "pre" in q.tags:
                continue
            a = ans.get(qid) or {"query_id": qid}
            sc = score(a, g, s, q); n += 1
            if q.slot == "downstream" and g.get("warranted"):
                prim["n"] += 1; e = g["assertion"] == []; prim["empty"] += e; prim["ok"] += sc["exact"]; prim["ok_nonempty"] += (sc["exact"] and not e)
            if sc["exact"]:
                tax["correct"] += 1; continue
            if sc["malformed"]:
                tax["malformed"] += 1; continue
            gs, st = g["status"], a.get("status")
            if gs == "established":
                if g["assertion"] == []:
                    tax["convention: empty-set gold -> " + str(st)] += 1
                elif g["assertion"] is False:
                    tax["convention: established-false gold -> " + str(st)] += 1
                elif st == "established":
                    tax["wrong value (committed)"] += 1
                elif st in ("unresolved", "possible"):
                    tax["under-commit: gold value among alternatives" if g["assertion"] in (a.get("alternatives") or []) or norm(g["assertion"]) == norm(a.get("assertion")) else "under-commit: gold value absent"] += 1
                else:
                    tax["answered unknown on established"] += 1
            elif gs in ("unresolved", "possible"):
                if st == "established":
                    tax["premature commitment"] += 1
                elif st == gs:
                    tax["wrong alternative set"] += 1
                elif st == "unknown":
                    tax["answered unknown on unresolved"] += 1
                else:
                    tax["status confusion unresolved/possible"] += 1
            else:
                tax["gold unknown, answered " + str(st)] += 1
    conv = sum(v for k, v in tax.items() if k.startswith("convention"))
    out = {"n": n, "taxonomy": dict(tax), "convention_total": conv, "primary": {"n": prim["n"], "empty_gold": prim["empty"], "micro_exact": prim["ok"] / max(1, prim["n"]), "micro_exact_nonempty": prim["ok_nonempty"] / max(1, prim["n"] - prim["empty"])}}
    json.dump(out, open(os.path.join(outd, "_error_taxonomy_llm.json"), "w"), indent=1)
    print(n, "scored primary answers; convention total", conv, f"{100*conv/n:.1f}%")
    for k, v in tax.most_common():
        print(f"{v:6d} {100*v/n:6.1f}% {k}")
    print("primary:", out["primary"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
