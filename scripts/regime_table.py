"""Regime table: when is last-write-wins right? (free; structured systems on Setting 1 streams)

Every `current` query on a single-valued, non-derived key is classified from the HIDDEN generator
labels (world facts, per-report truth, poison ids) into one regime, decided by the admitted reports
on the key up to the query's belief time tau. Regimes (first match wins):
  no_conflict      0 or 1 admitted assertion, or all admitted assertions agree
  retraction       the latest-reported assertion was withdrawn (report or source retraction) by tau
  poisoning        the latest-reported assertion is an attacker injection
  delayed_report   the latest-reported assertion is true but reports an OLDER world fact than an
                   earlier report (report order != valid order)
  low_trust_error  the latest-reported assertion is erroneous and comes from a low-reliability source
  other_error      the latest-reported assertion is erroneous (standard/trusted source)
  stale_earlier    the latest assertion is true and newer, but an earlier assertion is erroneous
                   (recency right by luck of ordering)
  self_update      every admitted assertion is true, values differ because the world changed, all from
                   the SAME origin, report order = valid order
  multi_source_update  as self_update but from several origins
Per regime we report, for last-write-wins by report time (always-commit), last-write-wins by valid
anchor (temporal DB) and PALIMPSEST (P0c): accuracy against the hidden WORLD value at tau (what the
reviewer's argument is about) and exact match against the justified-belief GOLD; plus PALIMPSEST's
abstention rate and the gold status mix. Stream-level cluster bootstrap for the world-accuracy columns.

Usage: python scripts/regime_table.py data/setting1 [--limit N] [--poison]   -> data/regime_table.json
"""
import collections, glob, json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.model import load_stream, Query, Stream
from palimpsest.core import BeliefStore
from baselines.structured import TemporalDB
from baselines.references import always_commit
from eval.scorer import score, norm
from eval.metrics import bootstrap_mean
from palimpsest.support import SupportModel
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIMES = ["self_update", "multi_source_update", "delayed_report", "low_trust_error", "other_error", "stale_earlier", "retraction", "poisoning", "no_conflict"]


def world_value(world, entity, attr, t):
    facts = [w for w in world if w["entity"] == entity and w["attr"] == attr and w["t0"] <= t]
    if not facts:
        return None
    return max(facts, key=lambda w: w["t0"])["value"]


def fact_t0(world, entity, attr, value, t_rep):
    """Start time of the world fact a true report of `value` refers to (latest such fact before the report)."""
    facts = [w for w in world if w["entity"] == entity and w["attr"] == attr and w["value"] == value and w["t0"] <= t_rep]
    return max((w["t0"] for w in facts), default=None)


def classify(s: Stream, hidden, q: Query):
    key = (q.entity, q.attr, "")
    tau = q.tau
    all_obs = sorted((o for o in s.observations if o.kind == "assert" and o.key == key and o.t_rep <= tau), key=lambda o: (o.t_rep, o.id))
    admitted = [o for o in s.admitted(tau) if o.key == key]
    adm_ids = {o.id for o in admitted}
    if len(all_obs) <= 1 or len({norm(o.value) for o in all_obs}) == 1:
        return "no_conflict"
    latest = all_obs[-1]
    truth = hidden["truth"]
    if latest.id not in adm_ids:
        return "retraction"
    if latest.id in set(hidden.get("poison", [])):
        return "poisoning"
    earlier = [o for o in all_obs[:-1]]
    if truth.get(latest.id) is True:
        t_latest = fact_t0(hidden["world"], q.entity, q.attr, latest.value, latest.t_rep)
        for o in earlier:
            if truth.get(o.id) is True:
                t_o = fact_t0(hidden["world"], q.entity, q.attr, o.value, o.t_rep)
                if t_latest is not None and t_o is not None and t_latest < t_o:
                    return "delayed_report"
        if any(truth.get(o.id) is False for o in earlier):
            return "stale_earlier"
        origins = {s.sources[o.source].origin for o in all_obs}
        return "self_update" if len(origins) == 1 else "multi_source_update"
    cls = s.sources[latest.source].cls
    return "low_trust_error" if cls == "low" else "other_error"


def run(datadir, limit=None, out="data/regime_table.json", policy="P0c"):
    from revise_stream.gold import all_gold
    from revise_stream import oracle_v1
    files = sorted(f for f in glob.glob(os.path.join(datadir, "*.json")) if not f.endswith((".gold.json", ".hidden.json")) and os.path.basename(f) != "_stats.json")
    if limit:
        files = files[:limit]
    rows = collections.defaultdict(list)        # regime -> list of per-query dicts
    for f in files:
        s = load_stream(f)
        gold = json.load(open(f.replace(".json", ".gold.json")))
        if policy != "P0c":    # stored gold is P0c; recompute under the requested policy
            gold = all_gold(s, lambda st, t, keys=None: oracle_v1.interpretations(st, t, policy, keys))
        hidden = json.load(open(f.replace(".json", ".hidden.json")))
        store = BeliefStore(s, policy=policy)
        tdb = TemporalDB(s)
        sm = SupportModel()
        for q in s.queries:
            if q.slot != "current" or q.attr is None:
                continue
            spec = s.attributes[q.attr]
            if spec.derived or spec.cardinality != "single":
                continue
            reg = classify(s, hidden, q)
            wv = world_value(hidden["world"], q.entity, q.attr, q.t if q.t is not None else q.tau)
            g = gold[q.id]
            key = (q.entity, q.attr, "")
            latest_obs = sorted((o for o in s.observations if o.kind == "assert" and o.key == key and o.t_rep <= q.tau), key=lambda o: (o.t_rep, o.id))
            latest_val = norm(latest_obs[-1].value) if latest_obs else None
            rec = {"stream": s.stream_id, "gold_status": g["status"], "gold_matches_world": g["status"] == "established" and norm(g["assertion"]) == norm(wv)}
            pal = store.answer(q)
            # graded commitment: when PALIMPSEST is unresolved, commit to the alternative with the highest support
            argmax = dict(pal)
            margin = None
            if pal.get("status") == "unresolved" and pal.get("alternatives"):
                cands = [c for c in pal["alternatives"] if c is not None]
                if cands:
                    sup = sm.support(s, (q.entity, q.attr, ""), q.tau, cands, q.t)
                    best = max(cands, key=lambda c: sup[c])
                    srt = sorted(sup.values(), reverse=True)
                    margin = srt[0] - (srt[1] if len(srt) > 1 else 0.0)
                    argmax = {"query_id": q.id, "status": "established", "assertion": best, "alternatives": [], "provenance": pal.get("provenance", [])}
            rec["argmax_margin"] = margin
            for name, ans in (("always_commit", always_commit(s, q)), ("temporal_db", tdb.answer(q)), ("palimpsest", pal), ("palimpsest_argmax", argmax)):
                sc = score(ans, g, s, q)
                est = ans.get("status") == "established"
                rec[name] = {"world": int(est and norm(ans.get("assertion")) == norm(wv)),
                             "exact": sc["exact"], "abstain": int(not est),
                             "wrong_commit": int(est and norm(ans.get("assertion")) != norm(wv)),
                             "latest_commit": int(est and norm(ans.get("assertion")) == latest_val)}   # committed to the latest report's value (= the injected value in the poisoning regime)
            rows[reg].append(rec)
    table = {}
    for reg in REGIMES:
        rs = rows.get(reg, [])
        if not rs:
            continue
        by_stream = collections.defaultdict(list)
        for r in rs:
            by_stream[r["stream"]].append(r)
        cell = {"n": len(rs), "n_streams": len(by_stream), "gold_status": dict(collections.Counter(r["gold_status"] for r in rs)),
                "gold_matches_world": sum(r["gold_matches_world"] for r in rs) / len(rs)}
        for name in ("always_commit", "temporal_db", "palimpsest", "palimpsest_argmax"):
            per = [sum(r[name]["world"] for r in v) / len(v) for v in by_stream.values()]
            m, lo, hi = bootstrap_mean(per, n_boot=3000)
            cell[name] = {"world_acc": round(sum(r[name]["world"] for r in rs) / len(rs), 3), "world_acc_ci": [round(lo, 3), round(hi, 3)],
                          "exact": round(sum(r[name]["exact"] for r in rs) / len(rs), 3),
                          "abstain": round(sum(r[name]["abstain"] for r in rs) / len(rs), 3),
                          "wrong_commit": round(sum(r[name]["wrong_commit"] for r in rs) / len(rs), 3),
                          "latest_commit": round(sum(r[name]["latest_commit"] for r in rs) / len(rs), 3)}
        table[reg] = cell
    # risk-coverage over the disputed queries: order PALIMPSEST's argmax commitments by support margin
    disputed = [r for rs in rows.values() for r in rs if r["argmax_margin"] is not None]
    disputed.sort(key=lambda r: -r["argmax_margin"])
    rc = []
    for k in range(1, len(disputed) + 1):
        rc.append({"coverage": round(k / len(disputed), 3), "accuracy": round(sum(r["palimpsest_argmax"]["world"] for r in disputed[:k]) / k, 3), "lww_accuracy": round(sum(r["always_commit"]["world"] for r in disputed[:k]) / k, 3)})
    table["_risk_coverage_disputed"] = {"n": len(disputed), "curve": rc[:: max(1, len(rc) // 40)], "lww_full": round(sum(r["always_commit"]["world"] for r in disputed) / max(1, len(disputed)), 3),
                                        "argmax_full": round(sum(r["palimpsest_argmax"]["world"] for r in disputed) / max(1, len(disputed)), 3)}
    json.dump(table, open(os.path.join(ROOT, out), "w"), indent=1)
    print(f"{'regime':<22}{'n':>6}  {'LWW(report)':>12} {'LWW(valid)':>11} {'PAL world':>10} {'PAL abst':>9} {'PAL wrong':>10} {'argmax':>8} {'gold=world':>10}")
    for reg, c in table.items():
        if reg.startswith("_"):
            continue
        print(f"{reg:<22}{c['n']:>6}  {c['always_commit']['world_acc']:>12.3f} {c['temporal_db']['world_acc']:>11.3f} {c['palimpsest']['world_acc']:>10.3f} {c['palimpsest']['abstain']:>9.3f} {c['palimpsest']['wrong_commit']:>10.3f} {c['palimpsest_argmax']['world_acc']:>8.3f} {c['gold_matches_world']:>10.3f}")
    t = table["_risk_coverage_disputed"]; print(f"disputed queries: {t['n']}; argmax world-acc at full coverage {t['argmax_full']} vs LWW {t['lww_full']}; at 50% coverage {t['curve'][len(t['curve'])//2]}")
    return table


if __name__ == "__main__":
    a = sys.argv[1:]
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    run(a[0], limit, out=a[a.index("--out") + 1] if "--out" in a else "data/regime_table.json", policy=a[a.index("--policy") + 1] if "--policy" in a else "P0c")
