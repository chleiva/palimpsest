"""Run the Setting 2 pipeline.
  python scripts/run_setting2.py DATADIR OUTDIR --mock [--noise slot=0.05,missed_cue=0.1,...]   (free)
  python scripts/run_setting2.py DATADIR OUTDIR --bridge CHEAP_MODEL BACKBONE_MODEL [--limit N] [--no-llm-log] [--topk K]
"""
import json
import zlib, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nl.llm import MockClient, BridgeClient, PendingResponse
from nl.pipeline import Setting2, load_streams
from nl.extractor import mock_extractor_handler
from nl.adjudicator import parse_answer
from eval.metrics import bootstrap_mean, bootstrap_paired


def mock_clients(streams, noise):
    handlers = {s.stream_id: mock_extractor_handler(s, noise, seed=zlib.crc32(s.stream_id.encode()) & 0xffff) for s in streams}
    by_s = {s.stream_id: s for s in streams}

    def cheap(req):
        kind = req["id"].split(":")[0]
        if kind == "para":                       # identity paraphrase
            return req["messages"][0]["content"]
        if kind == "cue":                        # recover cues from the (templated) text with the deterministic markers
            from nl.paraphrase import CHANGE_MARKERS, CORR_MARKERS, DATE_RE
            line = req["messages"][0]["content"]; body = line.split("):", 1)[1]
            return json.dumps({"states_change": bool(CHANGE_MARKERS.search(body)), "states_correction": bool(CORR_MARKERS.search(body)),
                               "corrected_report_id": None, "has_date": bool(DATE_RE.search(body))})
        return "{}"

    def backbone(req):
        kind, sid = req["id"].split(":")[0], req["id"].split(":")[1]
        if kind == "ext":
            return handlers[sid](req)
        if kind in ("adj", "rep", "adjnl", "repnl"):   # mock adjudicator: always-commit behaviour in contract form
            from baselines.references import always_commit
            qid = req["id"].split(":")[2]
            s = by_s[sid]
            q = next(x for x in s.queries if x.id == qid)
            return json.dumps(always_commit(s, q))
        return "{}"
    return MockClient(cheap, "mock-cheap"), MockClient(backbone, "mock-backbone")


def summarise(res):
    keys = ["warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop", "malformed_rate", "prov_precision", "prov_recall", "cost_tokens", "cost_usd"]
    rep = {}
    for name, ms in res["per_stream"].items():
        rep[name] = {k: bootstrap_mean([x.get(k) for x in ms], n_boot=2000) for k in keys}
        rep[name]["n_warranted_per_stream"] = sum(x["n_warranted"] for x in ms) / len(ms)
    ex = res["extraction"]
    rep["_extraction"] = {k: sum(d[k] for d in ex) / len(ex) for k in ex[0] if isinstance(ex[0][k], (int, float))}
    return rep


def print_report(res, rep):
    keys = ["warranted_acc", "warranted_direct_acc", "resolvable_acc", "unresolved_acc", "commit_rate", "unsupported_prop", "malformed_rate"]
    short = {"warranted_acc": "warr_down", "warranted_direct_acc": "warr_direct", "resolvable_acc": "resolvable", "unresolved_acc": "unresolved",
             "commit_rate": "commit", "unsupported_prop": "unsup_prop", "malformed_rate": "malformed"}
    print(f"{'system':<22}" + "".join(f"{short[k]:>18}" for k in keys) + f"{'tok/stream':>12}{'$/stream':>10}")
    for name, r in rep.items():
        if name.startswith("_"):
            continue
        row = f"{name:<22}"
        for k in keys:
            m, lo, hi = r[k]
            row += f"{m:>8.3f} [{lo:.2f},{hi:.2f}]" if m == m else f"{'n/a':>18}"
        row += f"{r['cost_tokens'][0]:>12.0f}{r['cost_usd'][0]:>10.3f}"
        print(row)
    print("extraction:", {k: round(v, 3) for k, v in rep["_extraction"].items()})
    print(f"warranted downstream per stream: {rep['palimpsest']['n_warranted_per_stream']:.2f}")
    ps = res["per_stream"]
    if "log_llm_adjudicator" in ps:
        (d, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["log_llm_adjudicator"]], n_boot=2000)
        print(f"H1: palimpsest - log_llm on warranted downstream: {d:+.3f} [{lo:+.3f},{hi:+.3f}] over {n} streams")
    (d, lo, hi), n = bootstrap_paired([x["warranted_acc"] for x in ps["palimpsest"]], [x["warranted_acc"] for x in ps["palimpsest_noprop"]], n_boot=2000)
    print(f"propagation on - off: {d:+.3f} [{lo:+.3f},{hi:+.3f}] over {n} streams")


if __name__ == "__main__":
    a = sys.argv[1:]
    datadir, outdir = a[0], a[1]
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    streams = load_streams(datadir, limit)
    noise = {}
    if "--noise" in a:
        for kv in a[a.index("--noise") + 1].split(","):
            k, v = kv.split("="); noise[k] = float(v)
    topk = int(a[a.index("--topk") + 1]) if "--topk" in a else None
    if "--mock" in a:
        cheap, backbone = mock_clients(streams, noise)
    elif "--anthropic" in a:
        from nl.anthropic_client import AnthropicBatchClient
        i = a.index("--anthropic")
        ns = os.path.basename(os.path.normpath(outdir))
        cheap, backbone = AnthropicBatchClient(a[i + 1], namespace=ns), AnthropicBatchClient(a[i + 2], namespace=ns)
    else:
        i = a.index("--bridge")
        blocking = "--nonblocking" not in a
        cheap, backbone = BridgeClient(a[i + 1], blocking=blocking), BridgeClient(a[i + 2], blocking=blocking)
    pl = Setting2(outdir, cheap, backbone, log_topk=topk)
    if "--limit-systems" in a:   # run the LLM log only on the first N streams (e.g. matched-cost variant)
        streams_llm = streams[:int(a[a.index("--limit-systems") + 1])]
    else:
        streams_llm = streams
    t0 = time.time()
    try:
        for stage in ("render", "paraphrase", "cuecheck", "extract"):
            getattr(pl, stage)(streams); print(f"{stage} done ({time.time()-t0:.0f}s)", flush=True)
        nl_limit = int(a[a.index("--nl-limit") + 1]) if "--nl-limit" in a else None
        pl.run_systems(streams, with_llm_log=False, with_nl_log=False)
        pl.run_systems(streams_llm, with_llm_log="--no-llm-log" not in a, with_nl_log="--no-nl-log" not in a, nl_log_limit=nl_limit); print(f"systems done ({time.time()-t0:.0f}s)", flush=True)
    except PendingResponse as e:
        print(f"PENDING bridge response: {e} — ship bridge/requests/{e}.json to the worker, bring back bridge/responses/{e}.json, re-run.")
        sys.exit(3)
    res = pl.score(streams)
    rep = summarise(res)
    json.dump({"summary": {k: v for k, v in rep.items()}, "per_stream": res["per_stream"], "extraction": res["extraction"]},
              open(os.path.join(outdir, "_results.json"), "w"), indent=1, default=str)
    print_report(res, rep)
