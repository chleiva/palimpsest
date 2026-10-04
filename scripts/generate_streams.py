"""Generate Setting 1 streams with oracle gold. Usage: python scripts/generate_streams.py N OUTDIR [--policy P0]"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.generator import GenConfig, generate, select_queries, write_stream
from revise_stream.gold import all_gold
from revise_stream.model import stream_from_dict
from revise_stream import oracle_v1

def main(n: int, outdir: str, seed0: int = 0, n_queries: int = 40, quota=(0.30, 0.30, 0.40), prefix: str = "s1"):
    os.makedirs(outdir, exist_ok=True)
    t0 = time.time(); stats = []
    for seed in range(seed0, seed0 + n):
        cfg = GenConfig(); cfg.n_queries = n_queries
        d, hidden = generate(seed, cfg, stream_id=f"{prefix}_{seed:04d}")
        s = stream_from_dict(d)
        gold = all_gold(s, oracle_v1.interpretations)
        keep = set(select_queries(s, gold, n_queries, random.Random(seed), quota=quota))
        d["queries"] = [q for q in d["queries"] if q["id"] in keep]
        gold = {k: v for k, v in gold.items() if k in keep}
        write_stream(os.path.join(outdir, f"{d['stream_id']}.json"), d, hidden, gold)
        nq = len(d["queries"]); nw = sum(1 for g in gold.values() if g["warranted"])
        nu = sum(1 for g in gold.values() if g["status"] in ("unresolved", "possible"))
        stats.append({"seed": seed, "n_obs": d["meta"]["n_obs"], "n_q": nq, "warranted": nw, "unresolved": nu})
        if (seed - seed0) % 50 == 0:
            print(f"seed {seed}: obs={d['meta']['n_obs']} q={nq} warranted={nw} unresolved={nu}  ({time.time()-t0:.1f}s)", flush=True)
    with open(os.path.join(outdir, "_stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    import statistics as st
    print(f"done {n} streams in {time.time()-t0:.1f}s; mean obs={st.mean(x['n_obs'] for x in stats):.1f} "
          f"mean q={st.mean(x['n_q'] for x in stats):.1f} mean warranted/stream={st.mean(x['warranted'] for x in stats):.2f} "
          f"mean unresolved/stream={st.mean(x['unresolved'] for x in stats):.1f}")

if __name__ == "__main__":
    a = sys.argv
    kw = {}
    if "--seed0" in a: kw["seed0"] = int(a[a.index("--seed0") + 1])
    if "--n_queries" in a: kw["n_queries"] = int(a[a.index("--n_queries") + 1])
    if "--quota" in a: kw["quota"] = tuple(float(x) for x in a[a.index("--quota") + 1].split(","))
    if "--prefix" in a: kw["prefix"] = a[a.index("--prefix") + 1]
    main(int(a[1]), a[2], **kw)
