"""Registered secondary hypotheses H2-H4 with stream-level cluster-bootstrap p-values and Holm
correction (reviewer v0.4, issue 6), from cached outputs. Also: field-by-field agreement between
the incremental store and symbolic replay on cached Setting 2/3 answers (status, assertion,
alternatives, provenance) and the reliability-diagram bins for Appendix figures.

H2  crossover ratio r* < 1 (raw-report adjudication vs extraction+store, LLM-token cost):
    bootstrap streams, recompute r* = E / A_nl from resampled per-stream means; p = P(r* >= 1).
H3  ECE(support) < ECE(verbalised) on the same queries: cluster bootstrap of the ECE difference;
    p = P(diff >= 0)  (one-sided, as registered: "lower ECE").
H4a commit rate(PALIMPSEST) < commit rate(LLM log): paired per-stream; p = P(diff >= 0).
H4b resolvable accuracy(PALIMPSEST) >= resolvable(LLM log) - 0.03 (non-inferiority): p = P(diff < -0.03).
Holm over the family {H2, H3, H4} with H4 = max(p_H4a, p_H4b) (both components must hold).
Output: data/holm_tests.json
"""
import collections, glob, json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palimpsest.support import ece
from eval.scorer import norm
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = 10000


def cluster_boot(fn, clusters, rng):
    """fn(list of clusters) -> statistic; resample clusters with replacement."""
    out = []
    n = len(clusters)
    for _ in range(B):
        samp = [clusters[rng.randrange(n)] for _ in range(n)]
        out.append(fn(samp))
    return out


def main():
    rng = random.Random(0)
    res = {}
    r = json.load(open(os.path.join(ROOT, "data", "s2", "_results.json")))
    ps = r["per_stream"]
    # H4
    pal, log = ps["palimpsest"], ps["log_llm_adjudicator"]
    pairs = [(a, b) for a, b in zip(pal, log)]
    d_commit = cluster_boot(lambda S: sum(a["commit_rate"] - b["commit_rate"] for a, b in S if a["commit_rate"] is not None and b["commit_rate"] is not None) / max(1, sum(1 for a, b in S if a["commit_rate"] is not None and b["commit_rate"] is not None)), pairs, rng)
    d_res = cluster_boot(lambda S: sum(a["resolvable_acc"] - b["resolvable_acc"] for a, b in S) / len(S), pairs, rng)
    p_h4a = sum(1 for x in d_commit if x >= 0) / B
    p_h4b = sum(1 for x in d_res if x < -0.03) / B
    res["H4a_commit"] = {"estimate": sum(a["commit_rate"] - b["commit_rate"] for a, b in pairs if a["commit_rate"] is not None) / len(pairs), "ci": [sorted(d_commit)[int(0.025 * B)], sorted(d_commit)[int(0.975 * B)]], "p_one_sided": p_h4a}
    res["H4b_resolvable_noninf"] = {"estimate": sum(a["resolvable_acc"] - b["resolvable_acc"] for a, b in pairs) / len(pairs), "ci": [sorted(d_res)[int(0.025 * B)], sorted(d_res)[int(0.975 * B)]], "p_one_sided": p_h4b, "margin": -0.03}
    # H2: r* = E / A_nl, E = extraction tokens per stream (palimpsest cost_tokens), A_nl = raw-report adjudication tokens per query
    nl = ps["log_nl_adjudicator"]
    cl = [(a["cost_tokens"], b["adj_tokens_per_query"]) for a, b in zip(pal[:len(nl)], nl) if b.get("adj_tokens_per_query")]
    rstar = cluster_boot(lambda S: (sum(e for e, _ in S) / len(S)) / (sum(a for _, a in S) / len(S)) / 131.0, cl, rng)
    # r* in queries per observation: E / (A_nl * n_obs); n_obs mean 131 (as in the crossover analysis)
    res["H2_crossover"] = {"estimate": (sum(e for e, _ in cl) / len(cl)) / (sum(a for _, a in cl) / len(cl)) / 131.0, "ci": [sorted(rstar)[int(0.025 * B)], sorted(rstar)[int(0.975 * B)]], "p_one_sided": sum(1 for x in rstar if x >= 1) / B, "n_streams": len(cl)}
    # H3: ECE difference, clustered by stream
    rq = json.load(open(os.path.join(ROOT, "data", "s2", "_rq3.json")))
    by = collections.defaultdict(lambda: {"sup": [], "verb": []})
    for p, y, sid in rq["support_on_extracted"]["pairs"]:
        by[sid]["sup"].append((p, y))
    for p, y, sid in rq["verbalised"]["pairs"]:
        by[sid]["verb"].append((p, y))
    clusters = list(by.values())

    def ece_diff(S):
        sup = [x for c in S for x in c["sup"]]; verb = [x for c in S for x in c["verb"]]
        return ece(sup) - ece(verb)
    d_ece = cluster_boot(ece_diff, clusters, rng)
    res["H3_ece"] = {"estimate": ece_diff(clusters), "ci": [sorted(d_ece)[int(0.025 * B)], sorted(d_ece)[int(0.975 * B)]], "p_one_sided": sum(1 for x in d_ece if x >= 0) / B, "n_streams": len(clusters)}
    # Holm over {H2, H3, H4}
    fam = {"H2": res["H2_crossover"]["p_one_sided"], "H3": res["H3_ece"]["p_one_sided"], "H4": max(p_h4a, p_h4b)}
    order = sorted(fam, key=lambda k: fam[k])
    adj = {}
    running = 0.0
    for i, k in enumerate(order):
        a = min(1.0, (3 - i) * fam[k]); running = max(running, a); adj[k] = running
    res["holm"] = {"raw": fam, "adjusted": adj, "alpha": 0.05, "rejected": {k: adj[k] < 0.05 for k in fam}}
    # field-by-field agreement store vs replay (cached answers)
    agree = {}
    for setting, outd in (("setting2_100", "s2"), ("setting3", "s3")):
        c = collections.Counter()
        for d in sorted(glob.glob(os.path.join(ROOT, "data", outd, "s*_*"))):
            try:
                A = json.load(open(os.path.join(d, "answers.json")))
            except Exception:
                continue
            for qid, a in A["palimpsest"].items():
                b = A["log_rule_adjudicator"].get(qid, {})
                c["n"] += 1
                c["status"] += a.get("status") == b.get("status")
                c["assertion"] += norm(a.get("assertion")) == norm(b.get("assertion"))
                c["alternatives"] += norm(a.get("alternatives")) == norm(b.get("alternatives"))
                c["provenance"] += sorted(a.get("provenance") or []) == sorted(b.get("provenance") or [])
        agree[setting] = {k: (v / c["n"] if k != "n" else v) for k, v in c.items()}
    res["store_vs_replay_fields"] = agree
    # reliability bins (15 equal-mass) for the appendix figure
    def bins(pairs, k=15):
        pp = sorted(pairs); out = []
        for i in range(k):
            chunk = pp[i * len(pp) // k:(i + 1) * len(pp) // k]
            if chunk:
                out.append({"conf": sum(p for p, _ in chunk) / len(chunk), "acc": sum(y for _, y in chunk) / len(chunk), "n": len(chunk)})
        return out
    res["reliability"] = {"support": bins([(p, y) for p, y, _ in rq["support_on_extracted"]["pairs"]]), "verbalised": bins([(p, y) for p, y, _ in rq["verbalised"]["pairs"]]),
                          "sampling": bins([(p, y) for p, y, _ in rq["sampling_k5"]["pairs"]])}
    json.dump(res, open(os.path.join(ROOT, "data", "holm_tests.json"), "w"), indent=1)
    for k in ("H2_crossover", "H3_ece", "H4a_commit", "H4b_resolvable_noninf"):
        print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in res[k].items()})
    print("Holm", res["holm"]); print("fields", agree)


if __name__ == "__main__":
    main()
