"""Poisoning (secondary RQ, Setting 1, free). Attacker injects false assertions at a rate
through a low-trust channel or a compromised trusted channel (half with a false change
cue). Reports, per system: world accuracy of established answers on value slots,
share of answers that assert a poisoned value as established (harmful commitment),
unresolved share, and mean support assigned to poisoned vs honest candidate values."""
import json, os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.generator import GenConfig, generate, select_queries
from revise_stream.gold import all_gold
from revise_stream.model import stream_from_dict
from revise_stream import oracle_v1
from palimpsest.core import BeliefStore
from palimpsest.support import SupportModel
from baselines.structured import TemporalDB
from baselines.references import always_commit
from scripts.run_rq3 import world_value


def run(rate, channel, n=60, seed0=5000):
    rows = {"palimpsest": [], "temporal_db": [], "always_commit": []}
    sup_p, sup_h = [], []
    model = SupportModel()
    for seed in range(seed0, seed0 + n):
        cfg = GenConfig(attack_rate=rate, attack_channel=channel)
        d, hidden = generate(seed, cfg, stream_id=f"poison_{channel}_{rate}_{seed}")
        s = stream_from_dict(d)
        gold = all_gold(s, oracle_v1.interpretations)
        keep = set(select_queries(s, gold, 40, random.Random(seed)))
        qs = [q for q in s.queries if q.id in keep and q.slot in ("current", "asof") and "pre" not in q.tags
              and s.attributes[q.attr].cardinality == "single" and not s.attributes[q.attr].derived]
        poison = set(hidden["poison"])
        pvals = {(o.entity, o.attr): o.value for o in s.observations if o.id in poison}
        systems = {"palimpsest": BeliefStore(s), "temporal_db": TemporalDB(s)}
        for name in rows:
            s.invalidate()
            acc, harm, unres, n_est = 0, 0, 0, 0
            for q in sorted(qs, key=lambda q: (q.tau, q.id)):
                a = systems[name].answer(q) if name in systems else always_commit(s, q)
                t = q.t if q.t is not None else q.tau
                truth = world_value(hidden, q.entity, q.attr, t)
                if a["status"] == "established":
                    n_est += 1
                    acc += int(a["assertion"] == truth)
                    harm += int(a["assertion"] == pvals.get((q.entity, q.attr)) and a["assertion"] != truth)
                else:
                    unres += 1
            rows[name].append({"world_acc_est": acc / max(1, n_est), "harm_rate": harm / max(1, len(qs)), "unresolved_share": unres / max(1, len(qs))})
        for q in qs:
            key = (q.entity, q.attr, q.ctx)
            g = gold[q.id]
            cands = [g["assertion"]] if g["status"] == "established" else [a for a in g["alternatives"] if a is not None]
            sp = model.support(s, key, q.tau, cands)
            for v, p in sp.items():
                (sup_p if v == pvals.get((q.entity, q.attr)) and v != world_value(hidden, q.entity, q.attr, q.t if q.t is not None else q.tau) else sup_h).append(p)
    out = {name: {k: st.mean(r[k] for r in rs) for k in rs[0]} for name, rs in rows.items()}
    out["support_poisoned_mean"] = st.mean(sup_p) if sup_p else None
    out["support_honest_mean"] = st.mean(sup_h) if sup_h else None
    return out


if __name__ == "__main__":
    res = {}
    for channel in ("low", "trusted"):
        for rate in (0.01, 0.05, 0.20):
            r = run(rate, channel)
            res[f"{channel}@{rate}"] = r
            print(f"{channel:<8} rate={rate:<5} "
                  + " | ".join(f"{n}: acc_est={v['world_acc_est']:.3f} harm={v['harm_rate']:.3f} unres={v['unresolved_share']:.2f}" for n, v in r.items() if isinstance(v, dict))
                  + f" | support poisoned={r['support_poisoned_mean']:.2f} honest={r['support_honest_mean']:.2f}", flush=True)
    json.dump(res, open("data/poison_setting1.json", "w"), indent=1)
