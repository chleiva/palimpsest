"""RQ3 in Setting 2 (H3): claim-level calibration of PALIMPSEST support on extracted
claims vs (a) the LLM adjudicator's verbalised confidence and (b) sampling-based
confidence (agreement across k=5 adjudications at T=0.7), against the hidden world.

Stages (resumable through the bridge):  python scripts/rq3_setting2.py OUTDIR DATADIR MODEL [--n 1000] [--k 5]
  verb   : asks the adjudicator, for each sampled answered query, a confidence in [0,1] for its asserted value
  sample : k adjudications at T=0.7 for the same queries; confidence = share agreeing with the T=0 answer
  score  : Brier/ECE/AURC for support (PALIMPSEST candidates), verbalised, sampling; labels from the world
"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nl.llm import BridgeClient, PendingResponse, extract_json
from nl.anthropic_client import AnthropicBatchClient
from nl.adjudicator import adjudication_request, parse_answer
from nl.pipeline import Setting2, load_streams, _obs_from
from palimpsest.support import SupportModel, brier, ece, aurc
from revise_stream.model import stream_from_dict
from scripts.run_rq3 import world_value

CONF_SYSTEM = "You previously answered a query from an evidence log. Now output JSON only: {\"confidence\": <number in [0,1]>} — your probability that the asserted value is actually true in the world."


def main(outdir, datadir, model, n=1000, k=5):
    streams = load_streams(datadir)
    pl = Setting2(outdir, None, None)
    rng = random.Random(0)
    pool = []
    for s in streams:
        ans = pl._load(s.stream_id, "answers") or {}
        llm = ans.get("log_llm_adjudicator", {})
        hidden = json.load(open(s.meta["_path"].replace(".json", ".hidden.json")))
        for q in s.queries:
            if q.slot not in ("current", "asof") or "pre" in q.tags or s.attributes[q.attr].derived or s.attributes[q.attr].cardinality != "single":
                continue
            a = llm.get(q.id)
            if a and a.get("status") == "established" and a.get("assertion") is not None:
                t = q.t if q.t is not None else q.tau
                pool.append((s, q, a, world_value(hidden, q.entity, q.attr, t)))
    rng.shuffle(pool); pool_v = pool[:n]; pool_s = pool[:min(n, 300)]   # sampling (k calls each) on a smaller subset
    pool = pool_v
    cl = AnthropicBatchClient(model, namespace=os.path.basename(os.path.normpath(outdir)) + "_rq3")
    # (a) verbalised confidence
    reqs = []
    for s, q, a, truth in pool:
        es = pl.extracted_stream(s)
        base = adjudication_request(es, es.observations, q)
        reqs.append({"id": f"conf:{s.stream_id}:{q.id}", "system": base["system"],
                     "messages": base["messages"] + [{"role": "assistant", "content": json.dumps(a)}, {"role": "user", "content": CONF_SYSTEM}],
                     "max_tokens": 30, "temperature": 0.0})
    try:
        vres = cl.chat(reqs, tag="rq3_verb")
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    # (b) sampling
    reqs = []
    for s, q, a, truth in pool_s:
        es = pl.extracted_stream(s)
        base = adjudication_request(es, es.observations, q)
        for i in range(k):
            r = dict(base); r["id"] = f"samp:{s.stream_id}:{q.id}:{i}"; r["temperature"] = 0.7
            reqs.append(r)
    try:
        sres = cl.chat(reqs, tag="rq3_samp")
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    # score
    sup_pairs, verb_pairs, samp_pairs = [], [], []
    model_s = SupportModel()
    pool_s_ids = {(s.stream_id, q.id) for s, q, a, truth in pool_s}
    for s, q, a, truth in pool:
        es = pl.extracted_stream(s)
        key = (q.entity, q.attr, q.ctx)
        v = a["assertion"]
        p_sup = model_s.support(es, key, q.tau, [v])[v]
        sup_pairs.append((p_sup, int(v == truth), s.stream_id))
        c = (extract_json((vres.get(f"conf:{s.stream_id}:{q.id}") or {}).get("text") or "") or {}).get("confidence")
        try:
            c = float(c)
        except Exception:
            c = 0.5
        verb_pairs.append((min(1.0, max(0.0, c)), int(v == truth), s.stream_id))
        agree = 0
        for i in range(k):
            aa = parse_answer(q, (sres.get(f"samp:{s.stream_id}:{q.id}:{i}") or {}).get("text") or "")
            if aa and aa.get("assertion") == v and aa.get("status") == "established":
                agree += 1
        if (s.stream_id, q.id) in pool_s_ids:
            samp_pairs.append((agree / k, int(v == truth), s.stream_id))
    out = {}
    for name, pairs in (("support_on_extracted", sup_pairs), ("verbalised", verb_pairs), ("sampling_k5", samp_pairs)):
        pp = [(x, y) for x, y, _ in pairs]
        out[name] = {"n": len(pp), "brier": brier(pp), "ece": ece(pp), "aurc": aurc(pp), "pairs": pairs}   # pairs kept with stream ids for clustered tests
        print(f"{name:<22} n={len(pp)} Brier={brier(pp):.3f} ECE={ece(pp):.3f} AURC={aurc(pp):.3f}")
    json.dump(out, open(os.path.join(outdir, "_rq3.json"), "w"), indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    n = int(a[a.index("--n") + 1]) if "--n" in a else 1000
    k = int(a[a.index("--k") + 1]) if "--k" in a else 5
    main(a[0], a[1], a[2], n, k)
