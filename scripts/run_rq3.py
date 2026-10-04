"""RQ3 — calibrated support (Setting 1, free). Claim-level evaluation against the hidden
world trajectory: for every value query whose gold is unresolved or established, each
candidate value v the oracle lists gets a support p(v); the label is whether v holds in
the world at the query's valid time. Comparators:
  support_default     declared class log-odds (no fitting)
  support_learned     class priors fitted on TRAIN streams (verified outcomes), evaluated on TEST
  class_prior_only    p = sigmoid(lo(best class asserting v)) with no grouping/recency/cues
  logreg_features     logistic regression on evidence features, trained on TRAIN streams
  always_half         p = 0.5 (reference)
Held-out: TEST streams use a different source roster mapping (source names/classes/origins
permuted) and the entity domain disjoint by seed range. Reports Brier, ECE, AURC.
Usage: python scripts/run_rq3.py data/setting1 [--train 0:300 --test 300:500]
"""
import glob, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from palimpsest.support import SupportModel, aurc, brier, ece, fit_class_priors, _sigmoid
from revise_stream.model import load_stream


def world_value(hidden, entity, attr, t):
    facts = sorted((f for f in hidden["world"] if f["entity"] == entity and f["attr"] == attr and f["t0"] <= t), key=lambda f: f["t0"])
    return facts[-1]["value"] if facts else None


def features(stream, key, tau, v, model):
    ev = model.evidence(stream, key, tau)
    obs = stream.admitted_by_key(tau).get(key, [])
    pro = [o for o in obs if o.value == v]
    con = [o for o in obs if o.value != v]
    classes = {"trusted": 3, "standard": 2, "low": 1}
    return [
        ev.get(v, 0.0), sum(w for k, w in ev.items() if k != v),
        len({stream.sources[o.source].origin for o in pro}), len({stream.sources[o.source].origin for o in con}),
        max((classes[stream.sources[o.source].cls] for o in pro), default=0),
        max((classes[stream.sources[o.source].cls] for o in con), default=0),
        1.0 if any(o.op_cue == "change" for o in pro) else 0.0,
        1.0 if any(o.op_cue == "correction" for o in con) else 0.0,
        (max(o.anchor for o in pro) - max(o.anchor for o in obs)) if pro else -60.0,
        1.0 if stream.attributes[key[1]].changeable else 0.0,
    ]


def logreg_fit(X, y, l2=1e-2, iters=400, lr=0.05):
    n, d = len(X), len(X[0])
    mu = [sum(x[j] for x in X) / n for j in range(d)]
    sd = [max(1e-6, (sum((x[j] - mu[j]) ** 2 for x in X) / n) ** 0.5) for j in range(d)]
    Z = [[(x[j] - mu[j]) / sd[j] for j in range(d)] for x in X]
    w, b = [0.0] * d, 0.0
    for _ in range(iters):
        gw, gb = [0.0] * d, 0.0
        for z, t in zip(Z, y):
            p = _sigmoid(sum(wi * zi for wi, zi in zip(w, z)) + b)
            g = p - t
            for j in range(d):
                gw[j] += g * z[j]
            gb += g
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return (w, b, mu, sd)


def logreg_predict(m, x):
    w, b, mu, sd = m
    z = [(x[j] - mu[j]) / sd[j] for j in range(len(x))]
    return _sigmoid(sum(wi * zi for wi, zi in zip(w, z)) + b)


def collect(paths, model, want_features=False):
    """Returns records: (stream, key, tau, v, label, feats)."""
    recs = []
    outcomes = []
    for p in paths:
        s = load_stream(p)
        gold = json.load(open(p.replace(".json", ".gold.json")))
        hidden = json.load(open(p.replace(".json", ".hidden.json")))
        # verified outcomes for learning class priors: every admitted assertion vs world
        for o in s.observations:
            if o.kind == "assert" and not s.attributes[o.attr].derived:
                wv = world_value(hidden, o.entity, o.attr, o.anchor)
                outcomes.append((s.sources[o.source].cls, wv == o.value))
        for q in s.queries:
            if q.slot not in ("current", "asof") or "pre" in q.tags or s.attributes[q.attr].derived:
                continue
            if s.attributes[q.attr].cardinality != "single":
                continue
            g = gold[q.id]
            cands = [g["assertion"]] if g["status"] == "established" else [a for a in g["alternatives"] if a is not None]
            if not cands:
                continue
            t = q.t if q.t is not None else q.tau
            truth = world_value(hidden, q.entity, q.attr, t)
            key = (q.entity, q.attr, q.ctx)
            for v in cands:
                recs.append((s, key, q.tau, v, int(v == truth), features(s, key, q.tau, v, model) if want_features else None))
    return recs, outcomes


def evaluate(name, pairs):
    print(f"  {name:<20} n={len(pairs):5d}  Brier={brier(pairs):.3f}  ECE={ece(pairs):.3f}  AURC={aurc(pairs):.3f}")
    return {"n": len(pairs), "brier": brier(pairs), "ece": ece(pairs), "aurc": aurc(pairs)}


def main(datadir, train=(0, 300), test=(300, 500)):
    paths = sorted(p for p in glob.glob(os.path.join(datadir, "*.json")) if not p.endswith((".gold.json", ".hidden.json", "_stats.json")))
    tr, te = paths[train[0]:train[1]], paths[test[0]:test[1]]
    base = SupportModel()
    rtr, otr = collect(tr, base, want_features=True)
    rte, _ = collect(te, base, want_features=True)
    learned = SupportModel(logodds=fit_class_priors(otr))
    print(f"train streams={len(tr)} test streams={len(te)}; learned class log-odds: { {k: round(v,2) for k,v in learned.lo.items()} }")
    out = {}
    print("TEST (held-out streams):")
    out["support_default"] = evaluate("support_default", [(base.support(s, k, tau, [v])[v], y) for s, k, tau, v, y, _ in rte])
    out["support_learned"] = evaluate("support_learned", [(learned.support(s, k, tau, [v])[v], y) for s, k, tau, v, y, _ in rte])
    prior_only = SupportModel(logodds=learned.lo, half_life_days=0, origin_grouping=False, use_cues=False)
    out["class_prior_only"] = evaluate("class_prior_only", [(prior_only.support(s, k, tau, [v])[v], y) for s, k, tau, v, y, _ in rte])
    m = logreg_fit([f for *_, f in rtr], [y for *_, y, _ in rtr])
    out["logreg_features"] = evaluate("logreg_features", [(logreg_predict(m, f), y) for *_, y, f in rte])
    out["always_half"] = evaluate("always_half", [(0.5, y) for *_, y, _ in rte])
    # ablations of the support model (held-out)
    for nm, kw in (("no_origin_grouping", {"origin_grouping": False}), ("no_recency", {"half_life_days": 0}), ("no_cues", {"use_cues": False})):
        mm = SupportModel(logodds=learned.lo, **kw)
        out["ablation_" + nm] = evaluate("abl:" + nm, [(mm.support(s, k, tau, [v])[v], y) for s, k, tau, v, y, _ in rte])
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    res = main(a[0])
    json.dump(res, open(os.path.join(a[0], "..", "rq3_setting1.json"), "w"), indent=1)
