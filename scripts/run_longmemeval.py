"""External check: LongMemEval knowledge-update subset (oracle version: evidence sessions only).

Data: bridge/data/longmemeval_oracle.json, downloaded by hand (3 Oct 2026) from
https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned (the "cleaned" release; the
original repo path no longer serves the file). No AWS/Bedrock involved: all LLM calls go
through nl.anthropic_client (Message Batches, hard cap) with Claude Haiku 4.5.

Adapter (shared by all systems): every user/assistant turn of the evidence sessions
becomes a report line in chronological order; an open-vocabulary extractor turns each
turn into zero or more claims about the entity 'user' (attribute = snake_case key,
value = short normalised string, optional change/correction cue); the question is
mapped by a cheap call to one extracted attribute key (the query slot). PALIMPSEST,
the temporal DB and the references answer the `current` slot from the extracted
claims; the LLM-adjudicated log answers from the claims log. Answers are judged against
the LongMemEval answer by a cheap-model judge (free-text), with 'unresolved' counted
as abstention (reported as coverage), so these numbers are NOT comparable to published
LongMemEval accuracies: the systems answer a structured slot, not the free question.

Usage: python scripts/run_longmemeval.py fetch | prepare | extract | answer | score  [--limit N]
"""
import json, os, re, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nl.llm import PendingResponse, extract_json
from nl.anthropic_client import AnthropicBatchClient
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BR = os.path.join(ROOT, "bridge"); OUT = os.path.join(ROOT, "data", "longmemeval")
DATA = os.path.join(BR, "data", "longmemeval_oracle.json")
CHEAP = os.environ.get("LME_CHEAP", "claude-haiku-4-5-20251001"); BACK = os.environ.get("LME_BACKBONE", "claude-haiku-4-5-20251001")


# v1 (no key merging; results_v1_nomerge.json) used tags lme_map/lme_adj/lme_judge; v2 adds the merge pass.
def _client(model):
    return AnthropicBatchClient(model, namespace="longmemeval")

OPEN_EXTRACT = """From ONE chat turn, list the durable facts it states about the user as JSON only:
{"claims": [{"attr": "<snake_case attribute, e.g. job_title, city, favorite_color, car_model>", "value": "<short lower-case value>",
 "op_cue": "none|change|correction", "op_from": "<previous value or null>"}]}
Include only facts about the user's own state or possessions (not opinions, not plans, not questions). Use "change" only when the turn
explicitly says something changed (used to / no longer / now / switched / moved / new). Use "correction" only when it says an earlier
statement was wrong. If the turn states no such fact, return {"claims": []}. Keep attribute names consistent and generic."""

MAP_Q = """Given a question about the user and a list of attribute keys, output JSON only: {"attr": "<the one key the question asks about, or null>"}."""

MERGE_KEYS = """You are given attribute keys extracted turn by turn from one user's chat history. Different turns often name the same
attribute differently (car, car_model, vehicle; job, job_title, occupation). Output JSON only: {"canonical": {"<key>": "<canonical key>", ...}}
mapping EVERY given key to a canonical key (a key maps to itself if it has no synonym). Merge only keys that denote the same attribute of
the user; keep genuinely different attributes apart."""

JUDGE = """You compare a system answer with a reference answer to the same question. Output JSON only: {"correct": true|false}.
The answer is correct if it conveys the same fact as the reference (minor wording differences are fine)."""


def _p(name):
    os.makedirs(OUT, exist_ok=True)
    return os.path.join(OUT, name)


def fetch():
    print(f"download longmemeval_oracle.json by hand into {DATA} (see module docstring)")


def prepare(limit=None):
    data = json.load(open(DATA))
    items = [x for x in data if x.get("question_type") == "knowledge-update"][:limit]
    out = []
    for x in items:
        turns = []
        sess = list(zip(x["haystack_dates"], x["haystack_sessions"], x["haystack_session_ids"]))
        sess.sort(key=lambda z: z[0])
        n = 0
        for di, (date, s, sid) in enumerate(sess):
            for t in s:
                n += 1
                turns.append({"id": f"o{n}", "day": di + 1, "date": date, "role": t["role"], "text": t["content"][:1500]})
        out.append({"qid": x["question_id"], "question": x["question"], "answer": x["answer"], "turns": turns})
    json.dump(out, open(_p("items.json"), "w"), indent=1)
    print(f"{len(out)} knowledge-update items, {sum(len(i['turns']) for i in out)} turns")


def extract():
    items = json.load(open(_p("items.json")))
    cl = _client(BACK)
    reqs = []
    for it in items:
        for t in it["turns"]:
            if t["role"] != "user":
                continue
            reqs.append({"id": f"lme:{it['qid']}:{t['id']}", "system": OPEN_EXTRACT, "messages": [{"role": "user", "content": t["text"]}], "max_tokens": 200, "temperature": 0.0})
    try:
        res = cl.chat(reqs, tag="lme_extract")
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    claims = {}
    for rid, v in res.items():
        d = extract_json(v.get("text") or "") or {}
        claims[rid] = [c for c in d.get("claims", []) if isinstance(c, dict) and c.get("attr") and c.get("value") is not None][:4]
    # canonicalise attribute keys per item (the turn-by-turn extractor names the same attribute inconsistently)
    reqs = []
    for it in items:
        keys = sorted({c["attr"] for rid, cs in claims.items() if rid.split(":")[1] == it["qid"] for c in cs})
        reqs.append({"id": f"merge:{it['qid']}", "system": MERGE_KEYS, "messages": [{"role": "user", "content": f"Keys: {keys}"}], "max_tokens": 600, "temperature": 0.0})
    try:
        res = _client(CHEAP).chat(reqs, tag="lme_merge")
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    canon = {rid.split(":")[1]: ((extract_json(v.get("text") or "") or {}).get("canonical") or {}) for rid, v in res.items()}
    n_merged = 0
    for rid, cs in claims.items():
        cm = canon.get(rid.split(":")[1], {})
        for c in cs:
            new = cm.get(c["attr"], c["attr"])
            if isinstance(new, str) and new != c["attr"]:
                c["attr"] = new; n_merged += 1
    print("keys merged:", n_merged)
    json.dump(claims, open(_p("claims.json"), "w"), indent=1)
    # map questions to attribute keys
    reqs = []
    for it in items:
        keys = sorted({c["attr"] for rid, cs in claims.items() if rid.split(":")[1] == it["qid"] for c in cs})
        reqs.append({"id": f"map:{it['qid']}", "system": MAP_Q, "messages": [{"role": "user", "content": f"Question: {it['question']}\nKeys: {keys}"}], "max_tokens": 40, "temperature": 0.0})
    try:
        res = _client(CHEAP).chat(reqs, tag="lme_map_v2")
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    qmap = {rid.split(":")[1]: (extract_json(v.get("text") or "") or {}).get("attr") for rid, v in res.items()}
    json.dump(qmap, open(_p("qmap.json"), "w"), indent=1)
    print("extraction done; mapped", sum(1 for v in qmap.values() if v), "of", len(qmap))


def _stream(it, claims, self_update=False):
    from revise_stream.model import stream_from_dict
    attrs = {}
    obs = []
    n = 0
    seen = set()
    for t in it["turns"]:
        for c in claims.get(f"lme:{it['qid']}:{t['id']}", []):
            a = re.sub(r"[^a-z0-9_]", "_", str(c["attr"]).lower())[:40]
            attrs[a] = {"type": "string", "cardinality": "single", "changeable": True, "error_allowed": True}
            n += 1
            o = {"id": f"o{n}", "t": t["day"], "source": "user", "kind": "assert", "entity": "user", "attr": a, "value": str(c["value"]).lower().strip()[:80]}
            if c.get("op_cue") in ("change", "correction") and c.get("op_cue") == "change":
                o["op_cue"] = "change"
                if c.get("op_from"):
                    o["op_from"] = str(c["op_from"]).lower().strip()[:80]
            elif self_update and a in seen:
                o["op_cue"] = "change"
            seen.add(a)
            obs.append(o)
    d = {"stream_id": f"lme_{it['qid']}", "domain": {"entities": ["user"], "attributes": attrs, "rules": []},
         "sources": {"user": {"class": "trusted", "origin": "user"}}, "observations": obs, "queries": []}
    return stream_from_dict(d), d


def answer():
    from palimpsest.core import BeliefStore
    from baselines.structured import TemporalDB
    from baselines.references import always_abstain, always_commit
    from nl.adjudicator import adjudication_request, parse_answer
    from revise_stream.model import Query
    items = json.load(open(_p("items.json"))); claims = json.load(open(_p("claims.json"))); qmap = json.load(open(_p("qmap.json")))
    answers = {}
    adj = []
    for it in items:
        a = qmap.get(it["qid"])
        s, d = _stream(it, claims)
        if not a or a not in s.attributes:
            answers[it["qid"]] = {"_unmapped": True}
            continue
        tau = max((o.t_rep for o in s.observations), default=1)
        q = Query(id="q", slot="current", tau=tau, entity="user", attr=a)
        d["queries"] = [{"id": "q", "slot": "current", "tau": tau, "entity": "user", "attr": a}]
        s.queries = [q]
        answers[it["qid"]] = {"palimpsest": BeliefStore(s).answer(q), "temporal_db": TemporalDB(s).answer(q),
                              "always_commit": always_commit(s, q), "always_abstain": always_abstain(s, q)}
        # exploratory variant (added after seeing v2; not pre-registered): a later self-report on a
        # single-valued changeable key is read as a stated change ("self-update" policy)
        s_su, _ = _stream(it, claims, self_update=True)
        s_su.queries = [q]
        answers[it["qid"]]["palimpsest_selfupdate"] = BeliefStore(s_su).answer(q)
        # graded commitment: on an unresolved answer commit to the alternative with the highest support; keep the margin
        pal = answers[it["qid"]]["palimpsest"]
        am = dict(pal); am["_margin"] = None
        if pal.get("status") == "unresolved" and [c for c in pal.get("alternatives", []) if c is not None]:
            from palimpsest.support import SupportModel
            cands = [c for c in pal["alternatives"] if c is not None]
            sup = SupportModel().support(s, ("user", a, ""), tau, cands, tau)
            best = max(cands, key=lambda c: sup[c]); srt = sorted(sup.values(), reverse=True)
            am = {"query_id": "q", "status": "established", "assertion": best, "alternatives": [], "provenance": pal.get("provenance", []), "_margin": srt[0] - (srt[1] if len(srt) > 1 else 0.0)}
        answers[it["qid"]]["palimpsest_argmax"] = am
        r = adjudication_request(s, s.observations, q); r["id"] = f"adj:{it['qid']}:q"
        r["messages"][0]["content"] += f"\n(The underlying question was: {it['question']})"
        adj.append(r)
    try:
        res = _client(BACK).chat(adj, tag="lme_adj_v2")
    except PendingResponse as e:
        json.dump(answers, open(_p("answers.json"), "w"), indent=1); print("PENDING", e); sys.exit(3)
    for rid, v in res.items():
        qid = rid.split(":")[1]
        answers[qid]["log_llm_adjudicator"] = parse_answer(Query(id="q", slot="current", tau=1), v.get("text") or "") or {"status": "malformed"}
    json.dump(answers, open(_p("answers.json"), "w"), indent=1)
    print("answers done")


def score():
    items = json.load(open(_p("items.json"))); answers = json.load(open(_p("answers.json")))
    reqs = []
    for it in items:
        a = answers.get(it["qid"], {})
        if a.get("_unmapped"):
            continue
        for sysn, ans in a.items():
            if ans.get("status") == "established" and ans.get("assertion") is not None:
                reqs.append({"id": f"judge:{it['qid']}:{sysn}", "system": JUDGE, "messages": [{"role": "user", "content": f"Question: {it['question']}\nReference answer: {it['answer']}\nSystem answer: {ans['assertion']}"}], "max_tokens": 20, "temperature": 0.0})
    main = [r for r in reqs if not r["id"].endswith((":palimpsest_selfupdate", ":palimpsest_argmax"))]
    extra = [r for r in reqs if r["id"].endswith(":palimpsest_selfupdate")]
    extra2 = [r for r in reqs if r["id"].endswith(":palimpsest_argmax")]
    try:
        res = _client(CHEAP).chat(main, tag="lme_judge_v2")
        res.update(_client(CHEAP).chat(extra, tag="lme_judge_v2_selfupdate") if extra else {})
        res.update(_client(CHEAP).chat(extra2, tag="lme_judge_v2_argmax") if extra2 else {})
    except PendingResponse as e:
        print("PENDING", e); sys.exit(3)
    verdict = {rid: bool((extract_json(v.get("text") or "") or {}).get("correct")) for rid, v in res.items()}
    out = {}
    n_total = len(items); n_mapped = sum(1 for it in items if not answers.get(it["qid"], {}).get("_unmapped"))
    # LongMemEval marks presupposition-false items with the suffix "_abs": the reference answer is
    # "the information provided is not enough", so abstaining (no established answer) is correct there.
    abs_items = {it["qid"] for it in items if it["qid"].endswith("_abs")}
    for sysn in ("palimpsest", "palimpsest_selfupdate", "palimpsest_argmax", "temporal_db", "always_commit", "always_abstain", "log_llm_adjudicator"):
        cov = corr = abs_corr = 0
        for it in items:
            a = answers.get(it["qid"], {}).get(sysn)
            if not a or a.get("status") != "established":
                if it["qid"] in abs_items and a is not None:
                    corr += 1; abs_corr += 1
                continue
            cov += 1; corr += int(verdict.get(f"judge:{it['qid']}:{sysn}", False))
        out[sysn] = {"coverage": cov / n_total, "accuracy_overall": corr / n_total, "accuracy_when_answered": (corr - abs_corr) / max(1, cov),
                     "abstention_items_correct": abs_corr, "n_abstention_items": len(abs_items)}
        print(f"{sysn:<22} coverage={cov/n_total:.2f} accuracy(all)={corr/n_total:.3f} accuracy(answered)={(corr-abs_corr)/max(1,cov):.3f} abs-items {abs_corr}/{len(abs_items)}")
    # risk-coverage over the disputed items, ordered by support margin (argmax) vs last-write-wins on the same items
    disp = [it for it in items if answers.get(it["qid"], {}).get("palimpsest", {}).get("status") == "unresolved" and answers[it["qid"]].get("palimpsest_argmax", {}).get("_margin") is not None]
    disp.sort(key=lambda it: -answers[it["qid"]]["palimpsest_argmax"]["_margin"])
    def ok(it, sysn):
        a = answers[it["qid"]].get(sysn, {})
        return int(a.get("status") == "established" and verdict.get(f"judge:{it['qid']}:{sysn}", False))
    curve = [{"coverage": round(k / len(disp), 3), "argmax_acc": round(sum(ok(x, "palimpsest_argmax") for x in disp[:k]) / k, 3), "lww_acc": round(sum(ok(x, "temporal_db") for x in disp[:k]) / k, 3)} for k in range(1, len(disp) + 1)]
    out["_risk_coverage_disputed"] = {"n": len(disp), "curve": curve}
    if curve:
        print(f"disputed items {len(disp)}: argmax acc at full coverage {curve[-1]['argmax_acc']} vs last-write-wins {curve[-1]['lww_acc']}; at half coverage {curve[len(curve)//2 - 1]}")
    out["_n_items"] = n_total; out["_n_mapped"] = n_mapped
    json.dump(out, open(_p("results.json"), "w"), indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    limit = int(a[a.index("--limit") + 1]) if "--limit" in a else None
    {"fetch": fetch, "prepare": lambda: prepare(limit), "extract": extract, "answer": answer, "score": score}[a[0]]()
