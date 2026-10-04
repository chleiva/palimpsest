"""Oracle validation (reviewer v0.4, issue 1): does the per-key factorisation produce exactly the
candidate sets of the GLOBAL semantics, including for derived slots?

Two computations of gold for every value query (current / downstream / asof / belief_asof) of
small generated streams and of the hand-written reference streams:
  per-key   the released oracle: per-key interpretation sets, rule engine branching over per-key
            candidate unions (revise_stream.gold with oracle_v1)
  global    brute force: every global TRUE/ERR + CONT/ENDED labelling of all admitted reports
            (oracle_v2._interpretations), and for EACH global interpretation the derived values are
            computed from that interpretation's own timelines for all keys at once (no mixing of
            interpretations across keys); candidates = union over global interpretations.
Any difference between the two is a counter-example to the factorisation. Streams are kept small
enough for 2^N enumeration (N admitted reports at the latest query time). Also reports the
product-structure check: |global set| == product over keys of |per-key sets|.
Usage: python scripts/oracle_validation.py [--n 300] [--max-obs 14]  -> data/oracle_validation.json
"""
import glob, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.model import stream_from_dict, load_stream, Query
from revise_stream.timeline import candidates_at, observed_candidates
from revise_stream.gold import gold_for, _norm_cands
from revise_stream import oracle_v1, oracle_v2
from revise_stream.generator import generate, GenConfig
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def global_value_gold(stream, tau, key, t):
    """Candidates for `key` at valid time t as the union over GLOBAL interpretations of the
    derivation under each interpretation's own timelines."""
    cands = set()
    for err, tls in oracle_v2._interpretations(stream, tau, "P0c"):
        tl = dict(tls)

        def prov(k, tt, _tl=tl):
            return observed_candidates(stream, _tl.get(k, ()), stream.attributes[k[1]], tt)
        cands |= candidates_at(stream, prov, key, t)
    alts = _norm_cands(stream, key[1], cands)
    if not alts or (len(alts) == 1 and alts[0] is None):
        return {"status": "unknown", "assertion": None, "alternatives": []}
    if len(alts) == 1:
        return {"status": "established", "assertion": alts[0], "alternatives": []}
    return {"status": "unresolved", "assertion": None, "alternatives": alts}


def product_check(stream, tau):
    full = oracle_v2._interpretations(stream, tau, "P0c")
    keys = sorted({o.key for o in stream.admitted(tau)})
    prod = 1
    for k in keys:
        prod *= len(oracle_v1.key_interpretations(stream, tau, k, "P0c"))
    return len(full), prod


def closure_substream(s, tau, key):
    """The stream restricted to the keys a query can depend on (the oracle's own dependency
    relation), plus every retraction or correction that refers into them. Under the semantics keys
    couple only through same-key relations and op_of/target references, so this is the global
    enumeration domain for the query; the product check below verifies the independence."""
    from revise_stream.gold import relevant_keys
    keys = {key} | set(relevant_keys(s, tau, key[0], key[1], key[2], oracle_v1.interpretations))
    keys = {k[:3] if len(k) > 3 else k for k in keys}
    ids = {o.id for o in s.observations if o.kind == "assert" and o.key in keys}
    keep = []
    for o in s.observations:
        if o.kind == "assert" and (o.key in keys or (o.op_of in ids)):
            keep.append(o)
        elif o.kind == "retract" and (o.target in ids or o.target in s.sources):
            keep.append(o)
    d = {"stream_id": s.stream_id + "_sub", "domain": {"entities": list(s.entities), "attributes": {a: _spec_dict(sp) for a, sp in s.attributes.items()}, "rules": s.meta.get("_rules_dict") or []},
         "sources": {k: {"class": v.cls, "origin": v.origin} for k, v in s.sources.items()}, "observations": [], "queries": []}
    sub = stream_from_dict(d)
    sub.rules = s.rules
    sub.observations = keep
    sub.invalidate()
    return sub


def _spec_dict(sp):
    return {"type": sp.type, "cardinality": sp.cardinality, "changeable": sp.changeable, "error_allowed": sp.error_allowed,
            "competing_values": sp.competing_values, "derived": sp.derived}


def check_stream(s, max_obs, out):
    qs = [q for q in s.queries if q.slot in ("current", "downstream", "asof", "belief_asof")]
    taus = sorted({q.tau_prime if q.slot == "belief_asof" else q.tau for q in qs})
    if not taus:
        return False
    for q in qs:
        tau = q.tau_prime if q.slot == "belief_asof" else q.tau
        t = q.t if q.slot == "asof" else (q.t if q.t is not None else tau)
        key = (q.entity, q.attr, q.ctx)
        sub = closure_substream(s, tau, key)
        n_adm = len(sub.admitted(tau))
        if n_adm > max_obs:
            out["n_skipped_large"] += 1
            continue
        g1 = gold_for(s, q, oracle_v1.interpretations)
        g1s = gold_for(sub, q, oracle_v1.interpretations)
        g2 = global_value_gold(sub, tau, key, t)
        out["n_queries"] += 1
        out["n_derived"] += int(s.attributes[q.attr].derived)
        out["max_enumerated"] = max(out["max_enumerated"], n_adm)
        if (g1["status"], g1["assertion"], g1["alternatives"]) != (g1s["status"], g1s["assertion"], g1s["alternatives"]):
            out["closure_failures"].append({"stream": s.stream_id, "query": q.id, "full": g1, "sub": g1s})
        if (g1s["status"], g1s["assertion"], g1s["alternatives"]) != (g2["status"], g2["assertion"], g2["alternatives"]):
            out["disagreements"].append({"stream": s.stream_id, "query": q.id, "slot": q.slot, "attr": q.attr, "per_key": g1s, "global": g2})
        n_full, prod = product_check(sub, tau)
        out["n_product_checks"] += 1
        if n_full != prod:
            out["product_failures"].append({"stream": s.stream_id, "query": q.id, "tau": tau, "global": n_full, "product": prod})
    return True


def main(n=300, max_obs=14):
    out = {"n_streams": 0, "n_queries": 0, "n_derived": 0, "disagreements": [], "n_product_checks": 0, "product_failures": [], "closure_failures": [], "n_skipped_large": 0, "max_enumerated": 0, "max_obs": max_obs}
    t0 = time.time()
    for path in sorted(os.listdir(os.path.join(ROOT, "revise_stream", "streams"))):
        if path.endswith(".json"):
            s = load_stream(os.path.join(ROOT, "revise_stream", "streams", path))
            s.meta["_rules_dict"] = json.load(open(os.path.join(ROOT, "revise_stream", "streams", path)))["domain"]["rules"]
            if check_stream(s, 18, out):
                out["n_streams"] += 1
    seed = 40000
    kept = 0
    while kept < n:
        cfg = GenConfig(seed=seed, T=30, n_persons=3, n_orgs=2, n_cities=4, max_obs_per_key=5, n_queries=40)
        d, _ = generate(seed, cfg, stream_id=f"ov_{seed}")
        seed += 1
        s = stream_from_dict(d)
        s.meta["_rules_dict"] = d["domain"]["rules"]
        if check_stream(s, max_obs, out):
            kept += 1; out["n_streams"] += 1
            if kept % 50 == 0:
                print(f"  {kept}/{n} streams, {out['n_queries']} queries, {len(out['disagreements'])} disagreements, {time.time()-t0:.0f}s", flush=True)
    # static exactness condition on every released domain + the shared-ancestor counter-example
    out["static_check"] = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "setting1", "s1_0000.json")) + glob.glob(os.path.join(ROOT, "data", "setting3", "s3_*[0-9].json"))[:1] + glob.glob(os.path.join(ROOT, "revise_stream", "streams", "*.json"))):
        out["static_check"][os.path.basename(path)] = body_closures_disjoint(load_stream(path))
    out["counterexample"] = counterexample()
    json.dump(out, open(os.path.join(ROOT, "data", "oracle_validation.json"), "w"), indent=1)
    print("static check:", out["static_check"]); print("counter-example:", out["counterexample"])
    print(f"streams {out['n_streams']}, value queries {out['n_queries']} ({out['n_derived']} on derived slots; {out['n_skipped_large']} skipped as too large; max enumerated {out['max_enumerated']} reports), "
          f"per-key vs global disagreements {len(out['disagreements'])}; closure failures {len(out['closure_failures'])}; product checks {out['n_product_checks']}, failures {len(out['product_failures'])}")
    for d in out["disagreements"][:5]:
        print(" ", d)


def body_closures_disjoint(stream):
    """Static exactness condition (ii): along any derivation path no base key is reached twice. Checked
    conservatively at the attribute level: for every rule, the sets of attributes reachable from its
    body atoms (through further rules) must be pairwise disjoint."""
    heads = {}
    for r in stream.rules:
        heads.setdefault(r.head[0], []).append(r)

    def reach(attr, seen=()):
        out = {attr}
        for r in heads.get(attr, []):
            for (a, _, _) in r.body:
                if a not in seen:
                    out |= reach(a, seen + (attr,))
        return out
    ok = True
    for r in stream.rules:
        sets = [reach(a) for (a, _, _) in r.body]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                if sets[i] & sets[j]:
                    ok = False
    return ok


def counterexample():
    """The reviewer's diagnostic: U <- X, V <- X, W <- U and V (a shared ancestor reached twice). The
    per-key factorisation must over-generate here, and the static check must flag the domain."""
    d = {"stream_id": "shared_ancestor", "domain": {"entities": ["p1"],
         "attributes": {"x": {"type": "string", "cardinality": "single", "changeable": False, "error_allowed": True},
                        "u": {"type": "string", "cardinality": "single", "changeable": False, "error_allowed": False, "derived": True},
                        "v": {"type": "string", "cardinality": "single", "changeable": False, "error_allowed": False, "derived": True},
                        "w": {"type": "string", "cardinality": "single", "changeable": False, "error_allowed": False, "derived": True}},
         "rules": [{"id": "ru", "kind": "strict", "head": ["u", "?e", "?a"], "body": [["x", "?e", "?a"]]},
                   {"id": "rv", "kind": "strict", "head": ["v", "?e", "?a"], "body": [["x", "?e", "?a"]]},
                   {"id": "rw", "kind": "strict", "head": ["w", "?e", "?a"], "body": [["u", "?e", "?a"], ["v", "?e", "?a"]]}]},
         "sources": {"s1": {"class": "standard", "origin": "s1"}, "s2": {"class": "standard", "origin": "s2"}},
         "observations": [{"id": "o1", "t": 1, "source": "s1", "kind": "assert", "entity": "p1", "attr": "x", "value": "A"},
                          {"id": "o2", "t": 2, "source": "s2", "kind": "assert", "entity": "p1", "attr": "x", "value": "B"}], "queries": []}
    s = stream_from_dict(d)
    q = Query(id="q", slot="downstream", tau=2, entity="p1", attr="w")
    g1 = gold_for(s, q, oracle_v1.interpretations)
    g2 = global_value_gold(s, 2, ("p1", "w", ""), 2)
    return {"static_check_passes": body_closures_disjoint(s), "per_key": g1, "global": g2}


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[a.index("--n") + 1]) if "--n" in a else 300, int(a[a.index("--max-obs") + 1]) if "--max-obs" in a else 14)
