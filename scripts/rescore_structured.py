"""Recompute the structured (LLM-free) systems on cached extracted streams and re-score, keeping the
cached LLM answers untouched. Used after a fix to the incremental store (3 Oct 2026: cross-key A-SELF
withdrawal). Writes <outdir>/_results.json (previous file kept as _results.prev.json) and prints the
per-query disagreements between the store and symbolic replay before/after.

Usage: python scripts/rescore_structured.py DATADIR OUTDIR [--topk K]
"""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nl.pipeline import Setting2, load_streams
from nl.llm import MockClient
from palimpsest.core import BeliefStore
from baselines.structured import LogQueryTime, TemporalDB
from baselines.references import always_abstain, always_commit
from eval.scorer import norm
from scripts.run_setting2 import summarise, print_report


def main(datadir, outdir, topk=None):
    streams = load_streams(datadir, None)
    pl = Setting2(outdir, MockClient(lambda r: ""), MockClient(lambda r: ""), log_topk=topk)
    before = after = 0
    for s in streams:
        A = pl._load(s.stream_id, "answers")
        if A is None:
            continue
        es = pl.extracted_stream(s)
        qs = sorted(es.queries, key=lambda q: (q.tau, q.id))
        systems = {"palimpsest": BeliefStore(es, propagation="on", policy=pl.policy),
                   "palimpsest_noprop": BeliefStore(es, propagation="off", policy=pl.policy),
                   "palimpsest_commit": BeliefStore(es, propagation="on", commit=True, policy=pl.policy),
                   "log_rule_adjudicator": LogQueryTime(es, policy=pl.policy), "temporal_db": TemporalDB(es)}
        for name, sysobj in systems.items():
            es.invalidate()
            A[name] = {q.id: sysobj.answer(q) for q in qs}
        es.invalidate(); A["always_abstain"] = {q.id: always_abstain(es, q) for q in qs}
        es.invalidate(); A["always_commit"] = {q.id: always_commit(es, q) for q in qs}
        for q in qs:
            p, r = A["palimpsest"][q.id], A["log_rule_adjudicator"][q.id]
            if (p.get("status"), norm(p.get("assertion"))) != (r.get("status"), norm(r.get("assertion"))):
                after += 1
        pl._save(s.stream_id, "answers", A)
    prev = os.path.join(outdir, "_results.json")
    if os.path.exists(prev):
        shutil.copy(prev, os.path.join(outdir, "_results.prev.json"))
    res = pl.score(streams)
    rep = summarise(res)
    json.dump({"summary": {k: v for k, v in rep.items()}, "per_stream": res["per_stream"], "extraction": res["extraction"]},
              open(prev, "w"), indent=1, default=str)
    print_report(res, rep)
    print(f"store-vs-replay disagreements after fix: {after}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], int(a[a.index("--topk") + 1]) if "--topk" in a else None)
