"""Systems benchmark (free, no LLM): incremental justification maintenance vs symbolic replay.

Three executions of the SAME semantics on the SAME streams and queries:
  incremental   palimpsest.core.BeliefStore — versions per key at write time, derived beliefs pin versions;
                queries read stored versions (ingest_until(tau) interleaves writes and reads in belief-time order)
  replay_cold   baselines.structured.LogQueryTime — recompute every key the query depends on from the log,
                per query, with the per-key cache cleared (pure query-time reasoning)
  replay_lazy   same, but the per-(key, tau) interpretation cache is kept across queries (cached recomputation)
Measured per stream and query/update ratio r (queries per observation): CPU time for writes and reads
(time.process_time), per-query latency distribution (mean, p95, max), peak memory (tracemalloc) over the
run, retained key/derived versions (incremental) or key recomputations (replay), and agreement of answers.
Workload: queries drawn at random over belief times 5..T and observed keys (70% direct `current`, 30%
derived `downstream`), sorted by belief time. Scale sweep: generated streams with more reports per key
and longer horizons. Output: data/systems_bench.json
Usage: python scripts/systems_bench.py [--streams N] [--ratios 0.1,0.33,1,3] [--scale]
"""
import glob, json, os, random, statistics, sys, time, tracemalloc
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from revise_stream.model import load_stream, stream_from_dict, Query
from revise_stream import oracle_v1
from palimpsest.core import BeliefStore
from baselines.structured import LogQueryTime
from eval.scorer import norm
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LazyReplay(LogQueryTime):
    """Query-time recomputation with the per-(key, tau) cache retained across queries."""
    def answer(self, q):
        from functools import partial
        from revise_stream.gold import gold_for
        from eval.scorer import supporting_ids
        s = self.s
        self.cost["reads"] += 1
        before = sum(1 for k in s._cache if isinstance(k, tuple) and k[0] == "kint")
        g = gold_for(s, q, partial(oracle_v1.interpretations, policy=self.policy))
        self.cost["key_recomputes"] += sum(1 for k in s._cache if isinstance(k, tuple) and k[0] == "kint") - before
        prov = g.get("provenance", []) if q.slot == "reported" else sorted(supporting_ids(s, q, g))
        return {"query_id": q.id, "status": g["status"], "assertion": g["assertion"], "alternatives": g.get("alternatives", []), "provenance": sorted(set(prov))}


def make_queries(s, n, rng):
    T = max(o.t_rep for o in s.observations)
    direct = sorted({(o.entity, o.attr) for o in s.observations if o.kind == "assert"})
    derived = [(e, a) for a, spec in s.attributes.items() if spec.derived for e in s.entities if e.startswith("p") or e.startswith("org") or e.startswith("Q")]
    qs = []
    for i in range(n):
        tau = rng.randint(5, T)
        if derived and rng.random() < 0.3:
            e, a = rng.choice(derived); qs.append(Query(id=f"b{i}", slot="downstream", tau=tau, entity=e, attr=a))
        else:
            e, a = rng.choice(direct); qs.append(Query(id=f"b{i}", slot="current", tau=tau, entity=e, attr=a))
    qs.sort(key=lambda q: (q.tau, q.id))
    return qs


def fresh(path_or_dict):
    return load_stream(path_or_dict) if isinstance(path_or_dict, str) else stream_from_dict(json.loads(json.dumps(path_or_dict)))


def run_system(name, src, qs):
    s = fresh(src)
    T = max(o.t_rep for o in s.observations)
    tracemalloc.start()
    res = {"name": name}
    t0 = time.process_time()
    if name == "incremental":
        sysobj = BeliefStore(s)
        sysobj.ingest_until(T) if not qs else None    # with queries, ingestion is interleaved by ingest_until(q.tau)
    else:
        sysobj = LogQueryTime(s) if name == "replay_cold" else LazyReplay(s)
    lat, answers = [], {}
    write_time = 0.0
    last_tau = 0
    for q in qs:
        if name == "incremental":
            w0 = time.process_time(); sysobj.ingest_until(q.tau); write_time += time.process_time() - w0
        a0 = time.process_time(); answers[q.id] = sysobj.answer(q); lat.append(time.process_time() - a0)
    if name == "incremental":
        w0 = time.process_time(); sysobj.ingest_until(T); write_time += time.process_time() - w0
    total = time.process_time() - t0
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    res.update({"cpu_total_s": total, "cpu_write_s": write_time, "cpu_read_s": sum(lat), "n_queries": len(qs),
                "lat_mean_ms": 1000 * statistics.mean(lat) if lat else 0.0, "lat_p95_ms": 1000 * sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else 0.0,
                "lat_max_ms": 1000 * max(lat) if lat else 0.0, "peak_mem_mb": peak / 1e6})
    if name == "incremental":
        res["versions_key"] = sum(len(v) for v in sysobj.keys.values()); res["versions_derived"] = sum(len(v) for v in sysobj.derived.values())
        res["key_recomputes"] = sysobj.cost["key_recomputes"]
    else:
        res["key_recomputes"] = sysobj.cost["key_recomputes"]
    return res, answers


def agree(a, b):
    return sum(1 for k in a if (a[k]["status"], norm(a[k]["assertion"])) == (b[k]["status"], norm(b[k]["assertion"]))), len(a)


def bench(sources, ratios, label, rng):
    out = []
    for i, src in enumerate(sources):
        s = fresh(src)
        n_obs = len(s.observations)
        for r in ratios:
            qs = make_queries(s, max(1, round(r * n_obs)), rng)
            row = {"workload": label, "stream": s.stream_id, "n_obs": n_obs, "ratio": r, "systems": {}}
            ans = {}
            for name in ("incremental", "replay_cold", "replay_lazy"):
                res, ans[name] = run_system(name, src, qs)
                row["systems"][name] = res
            row["agree_inc_vs_cold"] = agree(ans["incremental"], ans["replay_cold"])
            row["agree_inc_vs_lazy"] = agree(ans["incremental"], ans["replay_lazy"])
            out.append(row)
        if (i + 1) % 10 == 0:
            print(f"  {label}: {i + 1}/{len(sources)} streams", flush=True)
    return out


def summarise(rows):
    import collections
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["workload"], r["ratio"])].append(r)
    summ = {}
    for (wl, ratio), rs in sorted(by.items()):
        cell = {"n_streams": len(rs), "mean_obs": statistics.mean(r["n_obs"] for r in rs)}
        for name in ("incremental", "replay_cold", "replay_lazy"):
            xs = [r["systems"][name] for r in rs]
            cell[name] = {k: statistics.mean(x[k] for x in xs) for k in ("cpu_total_s", "cpu_write_s", "cpu_read_s", "lat_mean_ms", "lat_p95_ms", "peak_mem_mb", "key_recomputes")}
            cell[name]["lat_max_ms"] = max(x["lat_max_ms"] for x in xs)
            cell[name]["cpu_total_max_s"] = max(x["cpu_total_s"] for x in xs)
            if name == "incremental":
                cell[name]["versions_key"] = statistics.mean(x["versions_key"] for x in xs); cell[name]["versions_derived"] = statistics.mean(x["versions_derived"] for x in xs)
        cell["disagreements_inc_vs_cold"] = sum(r["agree_inc_vs_cold"][1] - r["agree_inc_vs_cold"][0] for r in rs)
        cell["n_answers"] = sum(r["agree_inc_vs_cold"][1] for r in rs)
        summ[f"{wl}|r={ratio}"] = cell
        print(f"{wl:<14} r={ratio:<5} obs={cell['mean_obs']:.0f}  " + "  ".join(f"{n[:9]}: total {cell[n]['cpu_total_s']:.2f}s lat {cell[n]['lat_mean_ms']:.1f}/{cell[n]['lat_p95_ms']:.1f}/{cell[n]['lat_max_ms']:.0f}ms mem {cell[n]['peak_mem_mb']:.1f}MB" for n in ("incremental", "replay_cold", "replay_lazy"))
              + f"  disagree {cell['disagreements_inc_vs_cold']}/{cell['n_answers']}", flush=True)
    return summ


if __name__ == "__main__":
    a = sys.argv[1:]
    n = int(a[a.index("--streams") + 1]) if "--streams" in a else 60
    ratios = [float(x) for x in a[a.index("--ratios") + 1].split(",")] if "--ratios" in a else [0.1, 0.33, 1.0, 3.0]
    rng = random.Random(0)
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "data", "setting1", "s1_*.json")) if not f.endswith((".gold.json", ".hidden.json")))[:n]
    rows = bench(files, ratios, "setting1", rng)
    if "--scale" in a:
        from revise_stream.generator import generate, GenConfig
        for mo, T in ((7, 60), (10, 60), (13, 60), (7, 120), (10, 120), (7, 240)):
            srcs = [generate(30000 + k, GenConfig(max_obs_per_key=mo, T=T), stream_id=f"scale_m{mo}_T{T}_{k}")[0] for k in range(5)]
            rows += bench(srcs, [1.0], f"scale_m{mo}_T{T}", rng)
    summ = summarise(rows)
    json.dump({"summary": summ, "rows": rows}, open(os.path.join(ROOT, "data", "systems_bench.json"), "w"), indent=1)
    print("written data/systems_bench.json")
