"""Amended-protocol reruns under the corrected output contract (reviewer P0-3) on ONE common subset,
plus the LLM baseline's cost/accuracy curve (reviewer P0-2). Original-protocol answers are kept under
their original system names; the reruns are stored as <name>_c2.

Setting 2: the first 30 streams of data/setting2_100 (the subset that already has the raw-report and
top-40 variants): full claims-log adjudicator, top-k with k in {10, 20, 40}, raw-report adjudicator.
Setting 3: all 30 streams: full claims-log and raw-report adjudicators.
All with Claude Haiku 4.5 (Message Batches), namespace = output dir, resumable: rerun until it stops
printing PENDING. Then: python scripts/rescore_structured.py is NOT needed; this script re-scores.
Usage: python scripts/rerun_contract.py data/setting2_100 data/s2 --subset 30
       python scripts/rerun_contract.py data/setting3 data/s3
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nl.pipeline import Setting2, load_streams
from nl.llm import PendingResponse
from nl.anthropic_client import AnthropicBatchClient
from scripts.run_setting2 import summarise, print_report

MODEL = "claude-haiku-4-5-20251001"


def main(datadir, outdir, subset=None):
    streams = load_streams(datadir, None)
    sub = streams[:subset] if subset else streams
    ns = os.path.basename(os.path.normpath(outdir))
    pl = Setting2(outdir, AnthropicBatchClient(MODEL, namespace=ns), AnthropicBatchClient(MODEL, namespace=ns))
    jobs = [("log_llm_adjudicator_c2", "adj_c2", "rep_c2", False, None)]
    if subset:
        jobs += [(f"log_llm_topk{k}_c2", f"adjtop{k}_c2", f"reptop{k}_c2", False, k) for k in (10, 20, 40)]
    jobs += [("log_nl_adjudicator_c2", "adjnl_c2", "repnl_c2", True, None)]
    pending = []
    for sysname, tag, rtag, nl, k in jobs:
        pl.log_topk = k
        try:
            pl._llm_log(sub, sysname, tag, rtag, nl=nl)
            print(f"{sysname}: done", flush=True)
        except PendingResponse as e:
            print(f"{sysname}: PENDING {e}", flush=True); pending.append(sysname)
    if pending:
        print("PENDING:", pending); sys.exit(3)
    res = pl.score(streams)
    rep = summarise(res)
    json.dump({"summary": {k: v for k, v in rep.items()}, "per_stream": res["per_stream"], "extraction": res["extraction"]},
              open(os.path.join(outdir, "_results.json"), "w"), indent=1, default=str)
    print_report(res, rep)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], int(a[a.index("--subset") + 1]) if "--subset" in a else None)
