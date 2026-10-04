"""Run all structured-setting systems on generated streams and evaluate the Phase 1 gate.
Usage: python scripts/run_setting1.py DATADIR [--limit N] [--out results.json]"""
import glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from baselines.references import always_abstain, always_commit
from baselines.structured import LogQueryTime, TemporalDB
from eval.metrics import bootstrap_mean, bootstrap_paired, stream_metrics
from eval.scorer import score
from palimpsest.core import BeliefStore
from revise_stream.model import load_stream


POLICY = "P0c"


def systems(stream):
    return {
        "palimpsest":        BeliefStore(stream, propagation="on", policy=POLICY),
        "palimpsest_noprop": BeliefStore(stream, propagation="off", policy=POLICY),
        "palimpsest_commit": BeliefStore(stream, propagation="on", commit=True, policy=POLICY),
        "log_query_time":    LogQueryTime(stream, policy=POLICY),
        "temporal_db":       TemporalDB(stream),
        "always_abstain":    type("A", (), {"answer": staticmethod(lambda q, s=stream: always_abstain(s, q)), "cost": {}})(),
        "always_commit":     type("C", (), {"answer": staticmethod(lambda q, s=stream: always_commit(s, q)), "cost": {}})(),
    }


def run(datadir: str, limit=None, out=None):
    paths = sorted(p for p in glob.glob(os.path.join(datadir, "*.json")) if not p.endswith((".gold.json", ".hidden.json", "_stats.json")))
    if limit:
        paths = paths[:limit]
    per_sys = {}
    t0 = time.time()
    for i, path in enumerate(paths):
        s = load_stream(path)
        if POLICY == "P0c":
            gold = json.load(open(path.replace(".json", ".gold.json")))
        else:   # sensitivity variant: recompute gold under the declared policy for the same frozen queries
            from functools import partial
            from revise_stream import oracle_v1
            from revise_stream.gold import all_gold
            gold = all_gold(s, partial(oracle_v1.interpretations, policy=POLICY))
        qs = sorted(s.queries, key=lambda q: (q.tau, q.id))
        for name, sys_ in systems(s).items():
            s.invalidate()
            answers = {}
            for q in qs:
                answers[q.id] = sys_.answer(q)
            scores = {q.id: score(answers[q.id], gold[q.id], s, q) for q in qs}
            m = stream_metrics(s, answers, gold, scores)
            m["cost"] = dict(getattr(sys_, "cost", {}))
            m["prov_precision"] = _mean([sc["prov_precision"] for sc in scores.values()])
            m["prov_recall"] = _mean([sc["prov_recall"] for sc in scores.values()])
            per_sys.setdefault(name, []).append(m)
        if i % 100 == 0:
            print(f"{i+1}/{len(paths)} streams ({time.time()-t0:.0f}s)", flush=True)
    report = summarise(per_sys)
    if out:
        json.dump({"per_stream": per_sys, "summary": report}, open(out, "w"), indent=1)
    return per_sys, report


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarise(per_sys):
    keys = ["warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop", "malformed_rate", "reported_acc", "prov_precision", "prov_recall"]
    rep = {}
    for name, ms in per_sys.items():
        rep[name] = {}
        for k in keys:
            m, lo, hi = bootstrap_mean([x[k] for x in ms], n_boot=2000)
            rep[name][k] = (m, lo, hi)
        rep[name]["n_warranted_per_stream"] = _mean([x["n_warranted"] for x in ms])
        rep[name]["n_warranted_direct_per_stream"] = _mean([x["n_warranted_direct"] for x in ms])
        rep[name]["cost"] = {ck: _mean([x["cost"].get(ck) for x in ms]) for ck in set().union(*[x["cost"].keys() for x in ms])}
        slots = set().union(*[x.get("slot_acc", {}).keys() for x in ms])
        rep[name]["slot_acc"] = {sl: _mean([x.get("slot_acc", {}).get(sl) for x in ms]) for sl in sorted(slots)}
    return rep


def print_report(per_sys, rep):
    keys = ["warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop", "prov_precision", "prov_recall"]
    short = {"warranted_acc": "warr_down", "warranted_direct_acc": "warr_direct", "resolvable_acc": "resolvable", "unresolved_acc": "unresolved",
             "commit_rate": "commit", "unsupported_prop": "unsup_prop", "prov_precision": "prov_P", "prov_recall": "prov_R"}
    print(f"{'system':<20}" + "".join(f"{short[k]:>18}" for k in keys))
    for name, r in rep.items():
        row = f"{name:<20}"
        for k in keys:
            m, lo, hi = r[k]
            row += f"{m:>8.3f} [{lo:.2f},{hi:.2f}]" if m == m else f"{'n/a':>18}"
        print(row)
    print("\ncost (mean work units per stream):")
    for name, r in rep.items():
        print(f"  {name:<20} {r['cost']}")
    print(f"\nwarranted queries per stream: downstream {rep['palimpsest']['n_warranted_per_stream']:.2f}, direct {rep['palimpsest']['n_warranted_direct_per_stream']:.2f}")
    # gate
    print("\nPhase 1 gate:")
    (d, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in per_sys["palimpsest"]], [x["warranted_acc"] for x in per_sys["palimpsest_noprop"]], n_boot=2000)
    print(f"  (a) propagation on - off, warranted accuracy: {d:+.3f} [{lo:+.3f},{hi:+.3f}] over {n} streams -> {'PASS' if lo > 0 else 'FAIL'}")
    ab, ac = rep["always_abstain"], rep["always_commit"]
    ok_b = ab["resolvable_acc"][0] < 0.05 and ab["unresolved_acc"][0] > ac["unresolved_acc"][0] and ac["resolvable_acc"][0] > ab["resolvable_acc"][0] + 0.3
    print(f"  (b) abstain: resolvable {ab['resolvable_acc'][0]:.3f} / unresolved {ab['unresolved_acc'][0]:.3f}; commit: resolvable {ac['resolvable_acc'][0]:.3f} / unresolved {ac['unresolved_acc'][0]:.3f} -> {'PASS' if ok_b else 'FAIL'}")
    (d, lo, hi), n = bootstrap_paired([x["unsupported_prop"] for x in per_sys["palimpsest_commit"]], [x["unsupported_prop"] for x in per_sys["palimpsest"]], n_boot=2000)
    print(f"  (c) forced-commit - palimpsest, unsupported propagation: {d:+.3f} [{lo:+.3f},{hi:+.3f}] over {n} streams -> {'PASS' if lo > 0 else 'FAIL'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    datadir = args[0]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    out = args[args.index("--out") + 1] if "--out" in args else None
    if "--policy" in args:
        POLICY = args[args.index("--policy") + 1]
    print(f"policy={POLICY}")
    per_sys, rep = run(datadir, limit, out)
    print_report(per_sys, rep)
