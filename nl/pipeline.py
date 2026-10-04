"""Setting 2 pipeline (natural-language streams, automatic extraction). Resumable stages:

  render      structured -> NL lines (free)
  paraphrase  LLM rewrite (cheap model)                       -> lines_para
  cuecheck    deterministic + cheap-model cue recovery; regenerate <=2; adjudicate (strip) -> frozen stream + gold
  extract     LLM extraction of every frozen line (backbone)  -> extracted observations (shared by all systems)
  systems     PALIMPSEST (on/off/commit), temporal DB, references on extracted claims (free);
              log + LLM adjudication (backbone), with one repair; log + rule adjudicator (free upper bound)
  score       contract scoring vs frozen gold, endpoints, extractor diagnostics, token costs

State lives in <outdir>/<stream_id>/*.json so any stage can be re-run.
"""
from __future__ import annotations

import json
import zlib
import os
import random
import time
from functools import partial
from typing import Any, Dict, List, Optional

from baselines.references import always_abstain, always_commit
from baselines.structured import LogQueryTime, TemporalDB
from eval.metrics import stream_metrics
from eval.scorer import score, validate
from nl.adjudicator import adjudication_request, parse_answer, repair_request
from nl.extractor import extraction_diagnostics, extraction_request, parse_extraction
from nl.paraphrase import cue_recovery_request, deterministic_cue_check, model_cue_check, paraphrase_request, strip_cues
from nl.templater import render_stream
from nl.llm import extract_json
from palimpsest.core import BeliefStore
from revise_stream import oracle_v1
from revise_stream.gold import all_gold
from revise_stream.model import Observation, Query, Stream, load_stream, stream_from_dict


def _obs_dict(o: Observation) -> dict:
    return {k: v for k, v in o.__dict__.items()}


def _obs_from(d: dict) -> Observation:
    return Observation(**d)


class Setting2:
    def __init__(self, outdir: str, client_cheap, client_backbone, policy: str = "P0c", log_topk: Optional[int] = None):
        self.out = outdir
        self.cheap, self.backbone = client_cheap, client_backbone
        self.policy = policy
        self.log_topk = log_topk
        os.makedirs(outdir, exist_ok=True)

    # ---------- helpers ----------
    def _p(self, sid: str, name: str) -> str:
        d = os.path.join(self.out, sid)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name + ".json")

    def _load(self, sid, name):
        p = self._p(sid, name)
        return json.load(open(p)) if os.path.exists(p) else None

    def _save(self, sid, name, obj):
        json.dump(obj, open(self._p(sid, name), "w"), indent=1)

    # ---------- stage 1: render ----------
    def render(self, streams: List[Stream]):
        for s in streams:
            if self._load(s.stream_id, "lines") is None:
                self._save(s.stream_id, "lines", render_stream(s, seed=zlib.crc32(s.stream_id.encode()) & 0xffff))

    # ---------- stage 2: paraphrase ----------
    def paraphrase(self, streams: List[Stream], attempt: int = 0):
        """attempt 0: every line; attempt k>0: only lines flagged by the cue check of attempt k-1."""
        items, where = [], {}
        for s in streams:
            lines = self._load(s.stream_id, "lines")
            para = self._load(s.stream_id, "para") or {}
            flagged = self._load(s.stream_id, f"flagged_a{attempt - 1}") if attempt > 0 else None
            for oid, line in lines.items():
                need = (oid not in para) if attempt == 0 else (oid in (flagged or {}))
                if need:
                    r = paraphrase_request(s.stream_id, oid, line)
                    r["id"] += f":a{attempt}"
                    items.append(r); where[r["id"]] = (s.stream_id, oid, line)
        if not items:
            return
        res = self.cheap.chat(items, tag=f"para_a{attempt}")
        by_stream: Dict[str, dict] = {}
        for rid, (sid, oid, line) in where.items():
            txt = (res.get(rid) or {}).get("text") or ""
            txt = txt.strip().split("\n")[0] if txt else line
            if not txt.startswith("["):          # the model dropped the prefix: restore it
                txt = line.split("):", 1)[0] + "): " + txt
            by_stream.setdefault(sid, {})[oid] = txt
        for sid, d in by_stream.items():
            para = self._load(sid, "para") or {}
            para.update(d)
            self._save(sid, "para", para)

    # ---------- stage 3: cue recovery + freeze ----------
    def cuecheck(self, streams: List[Stream], max_regen: int = 2):
        """Resumable across PendingResponse: per-attempt flag files and a state marker."""
        st_p = os.path.join(self.out, "_cuecheck_state.json")
        state = json.load(open(st_p)) if os.path.exists(st_p) else {"attempt": 0}
        by_s = {s.stream_id: s for s in streams}
        for attempt in range(state["attempt"], max_regen + 1):
            if attempt > 0:
                self.paraphrase(streams, attempt=attempt)     # apply (or wait for) the regeneration of lines flagged at attempt-1
            # deterministic check on the current paraphrases (saved once per attempt)
            items, where = [], {}
            for s in streams:
                if self._load(s.stream_id, f"flagged_a{attempt}") is not None and self._load(s.stream_id, f"flagged_det_a{attempt}") is not None:
                    continue
                para = self._load(s.stream_id, "para")
                det = {}
                for o in s.observations:
                    ok, why = deterministic_cue_check(o, para[o.id])
                    if not ok:
                        det[o.id] = why
                self._save(s.stream_id, f"flagged_det_a{attempt}", det)
            for s in streams:
                if self._load(s.stream_id, f"flagged_a{attempt}") is not None:
                    continue
                det = self._load(s.stream_id, f"flagged_det_a{attempt}")
                para = self._load(s.stream_id, "para")
                # model check: every line at attempt 0; afterwards only lines regenerated at this attempt
                regen = set(self._load(s.stream_id, f"flagged_a{attempt - 1}") or {}) if attempt > 0 else None
                for o in s.observations:
                    if o.id not in det and (regen is None or o.id in regen):
                        r = cue_recovery_request(s.stream_id, o.id, para[o.id]); r["id"] += f":a{attempt}"
                        items.append(r); where[r["id"]] = (s.stream_id, o.id)
            if items:
                res = self.cheap.chat(items, tag=f"cue_a{attempt}")
            else:
                res = {}
            model_flags: Dict[str, dict] = {}
            for rid, (sid, oid) in where.items():
                o = next(x for x in by_s[sid].observations if x.id == oid)
                ok, why = model_cue_check(o, extract_json((res.get(rid) or {}).get("text") or ""))
                if not ok:
                    model_flags.setdefault(sid, {})[oid] = why
            n_flag = 0
            for s in streams:
                if self._load(s.stream_id, f"flagged_a{attempt}") is None:
                    fl = dict(self._load(s.stream_id, f"flagged_det_a{attempt}"))
                    fl.update(model_flags.get(s.stream_id, {}))
                    self._save(s.stream_id, f"flagged_a{attempt}", fl)
                n_flag += len(self._load(s.stream_id, f"flagged_a{attempt}"))
            state = {"attempt": attempt + 1, "last_flags": n_flag}
            json.dump(state, open(st_p, "w"))
            if n_flag == 0 or attempt == max_regen:
                state["final_attempt"] = attempt
                json.dump(state, open(st_p, "w"))
                break
            self.paraphrase(streams, attempt=attempt + 1)    # regenerate flagged lines only (may raise Pending)
        final = state.get("final_attempt", min(state["attempt"] - 1, max_regen))
        # adjudicate: strip cues the text lost on the final attempt; freeze
        for s in streams:
            if self._load(s.stream_id, "frozen") is not None:
                continue
            flagged = self._load(s.stream_id, f"flagged_a{final}") or {}
            self._save(s.stream_id, "flagged", flagged)
            frozen = [strip_cues(o, flagged[o.id]) if o.id in flagged else o for o in s.observations]
            fs = stream_from_dict(json.load(open(s.meta["_path"])))
            fs.observations = frozen
            fs.invalidate()
            gold = all_gold(fs, partial(oracle_v1.interpretations, policy=self.policy))
            self._save(s.stream_id, "frozen", {"observations": [_obs_dict(o) for o in frozen], "flagged": flagged, "gold": gold})

    # ---------- stage 4: extraction ----------
    def extract(self, streams: List[Stream]):
        items, where = [], {}
        for s in streams:
            if self._load(s.stream_id, "extracted") is not None:
                continue
            para = self._load(s.stream_id, "para")
            for o in s.observations:
                r = extraction_request(s, o.id, para[o.id])
                items.append(r); where[r["id"]] = (s.stream_id, o.id)
        if items:
            res = self.backbone.chat(items, tag="ext")
            by_s = {s.stream_id: s for s in streams}
            per: Dict[str, dict] = {}
            for rid, (sid, oid) in where.items():
                o = next(x for x in by_s[sid].observations if x.id == oid)
                txt = (res.get(rid) or {}).get("text") or ""
                x, err = parse_extraction(by_s[sid], o, txt)
                per.setdefault(sid, {})[oid] = {"obs": _obs_dict(x) if x else None, "error": err, "raw": txt[:400],
                                                 "usage": (res.get(rid) or {}).get("usage")}
            for sid, d in per.items():
                self._save(sid, "extracted", d)

    def extracted_stream(self, s: Stream) -> Stream:
        """The stream every system sees: extracted claims (failed extractions dropped),
        same queries, frozen gold is separate."""
        ex = self._load(s.stream_id, "extracted")
        obs = [_obs_from(v["obs"]) for oid, v in ex.items() if v["obs"]]
        obs.sort(key=lambda o: (o.t_rep, int(o.id[1:])))
        d = json.load(open(s.meta["_path"]))
        es = stream_from_dict(d)
        es.observations = obs
        es.invalidate()
        return es

    # ---------- stage 5: systems ----------
    def run_systems(self, streams: List[Stream], with_llm_log: bool = True, with_nl_log: bool = True, nl_log_limit: Optional[int] = None):
        for s in streams:
            if self._load(s.stream_id, "answers") is not None:
                continue
            es = self.extracted_stream(s)
            qs = sorted(es.queries, key=lambda q: (q.tau, q.id))
            answers: Dict[str, Dict[str, dict]] = {}
            systems = {
                "palimpsest": BeliefStore(es, propagation="on", policy=self.policy),
                "palimpsest_noprop": BeliefStore(es, propagation="off", policy=self.policy),
                "palimpsest_commit": BeliefStore(es, propagation="on", commit=True, policy=self.policy),
                "log_rule_adjudicator": LogQueryTime(es, policy=self.policy),
                "temporal_db": TemporalDB(es),
            }
            for name, sy in systems.items():
                es.invalidate()
                answers[name] = {q.id: sy.answer(q) for q in qs}
            answers["always_abstain"] = {q.id: always_abstain(es, q) for q in qs}
            answers["always_commit"] = {q.id: always_commit(es, q) for q in qs}
            self._save(s.stream_id, "answers", answers)
        if with_llm_log:
            if self.log_topk:
                self._llm_log(streams, f"log_llm_topk{self.log_topk}", f"adjtop{self.log_topk}", f"reptop{self.log_topk}", nl=False)
            else:
                self._llm_log(streams, "log_llm_adjudicator", "adj", "rep", nl=False)
        if with_nl_log:
            self._llm_log(streams[:nl_log_limit] if nl_log_limit else streams, "log_nl_adjudicator", "adjnl", "repnl", nl=True)

    def _llm_log(self, streams: List[Stream], sysname: str, tag: str, rtag: str, nl: bool):
        adj_items, where = [], {}
        for s in streams:
            ans = self._load(s.stream_id, "answers")
            if sysname in ans:
                continue
            es = self.extracted_stream(s)
            qs = sorted(es.queries, key=lambda q: (q.tau, q.id))
            lines = self._load(s.stream_id, "para") if nl else None
            log = s.observations if nl else es.observations      # the NL log is the full report stream
            for q in qs:
                r = adjudication_request(es if not nl else s, log, q, topk=self.log_topk, nl_lines=lines)
                adj_items.append(r); where[r["id"]] = (s.stream_id, q.id)
        if not adj_items:
            return
        res = self.backbone.chat(adj_items, tag=tag)
        by_s = {s.stream_id: s for s in streams}
        reps, rwhere = [], {}
        parsed: Dict[str, dict] = {}
        for rid, (sid, qid) in where.items():
            q = next(x for x in by_s[sid].queries if x.id == qid)
            txt = (res.get(rid) or {}).get("text") or ""
            a = parse_answer(q, txt)
            usage = (res.get(rid) or {}).get("usage") or {}
            if a is None or validate(a) is not None:
                err = "no json" if a is None else validate(a)
                orig = next(it for it in adj_items if it["id"] == rid)
                rr = repair_request(orig, txt, err)
                reps.append(rr); rwhere[rr["id"]] = (sid, qid, usage)
            else:
                parsed.setdefault(sid, {})[qid] = {"answer": a, "usage": usage, "repaired": False}
        if reps:
            rres = self.backbone.chat(reps, tag=rtag)
            for rid, (sid, qid, usage0) in rwhere.items():
                q = next(x for x in by_s[sid].queries if x.id == qid)
                txt = (rres.get(rid) or {}).get("text") or ""
                a = parse_answer(q, txt)
                usage = (rres.get(rid) or {}).get("usage") or {}
                u = {"in": usage0.get("in", 0) + usage.get("in", 0), "out": usage0.get("out", 0) + usage.get("out", 0),
                     "cost_usd": usage0.get("cost_usd", 0) + usage.get("cost_usd", 0)}
                if a is None or validate(a) is not None:
                    a = {"query_id": qid, "status": "malformed"}          # scored as malformed (wrong everywhere)
                parsed.setdefault(sid, {})[qid] = {"answer": a, "usage": u, "repaired": True}
        for sid, d in parsed.items():
            ans = self._load(sid, "answers")
            ans[sysname] = {qid: v["answer"] for qid, v in d.items()}
            self._save(sid, "answers", ans)
            self._save(sid, f"usage_{sysname}", {qid: {"usage": v["usage"], "repaired": v["repaired"]} for qid, v in d.items()})

    # ---------- stage 6: score ----------
    def score(self, streams: List[Stream]) -> Dict[str, Any]:
        per_sys: Dict[str, List[dict]] = {}
        diags = []
        for s in streams:
            fro = self._load(s.stream_id, "frozen")
            gold = fro["gold"]
            fs = stream_from_dict(json.load(open(s.meta["_path"])))
            fs.observations = [_obs_from(d) for d in fro["observations"]]
            fs.invalidate()
            answers = self._load(s.stream_id, "answers")
            ex = self._load(s.stream_id, "extracted")
            diags.append(extraction_diagnostics(fs, fs.observations, {oid: (_obs_from(v["obs"]) if v["obs"] else None) for oid, v in ex.items()}))
            ext_tokens = sum(((v.get("usage") or {}).get("in", 0) + 8 * (v.get("usage") or {}).get("out", 0)) for v in ex.values())
            ext_cost = sum(((v.get("usage") or {}).get("cost_usd", 0)) for v in ex.values())
            for name, ans in answers.items():
                if not ans:
                    continue
                sc = {}
                for q in fs.queries:
                    a = ans.get(q.id)
                    sc[q.id] = score(a if a else {"query_id": q.id}, gold[q.id], fs, q)
                m = stream_metrics(fs, ans, gold, sc)
                is_nl = name.startswith("log_nl_adjudicator")       # raw-report log: no extraction cost
                m["cost_tokens"] = 0 if is_nl else ext_tokens
                m["cost_usd"] = 0.0 if is_nl else ext_cost
                m["n_obs"] = len(fs.observations)
                if name.startswith("log_llm") or is_nl:
                    adj = self._load(s.stream_id, f"usage_{name}") or {}
                    m["cost_tokens"] += sum(v["usage"].get("in", 0) + 8 * v["usage"].get("out", 0) for v in adj.values())
                    m["cost_usd"] += sum(v["usage"].get("cost_usd", 0) for v in adj.values())
                    m["adj_tokens_per_query"] = (sum(v["usage"].get("in", 0) + 8 * v["usage"].get("out", 0) for v in adj.values()) / max(1, len(adj)))
                    m["repair_rate"] = sum(1 for v in adj.values() if v["repaired"]) / max(1, len(adj))
                m["prov_precision"] = _mean([x["prov_precision"] for x in sc.values()])
                m["prov_recall"] = _mean([x["prov_recall"] for x in sc.values()])
                per_sys.setdefault(name, []).append(m)
        return {"per_stream": per_sys, "extraction": diags}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def load_streams(datadir: str, limit: Optional[int] = None) -> List[Stream]:
    import glob
    paths = sorted(p for p in glob.glob(os.path.join(datadir, "*.json")) if not p.endswith((".gold.json", ".hidden.json", "_stats.json")))
    if limit:
        paths = paths[:limit]
    out = []
    for p in paths:
        s = load_stream(p)
        s.meta["_path"] = p
        out.append(s)
    return out
