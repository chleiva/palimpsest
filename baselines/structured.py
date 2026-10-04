"""Structured-setting baselines (Phase 1).

log_query_time: append-only evidence log with a complete rule-based adjudicator run
    at query time (in Setting 1 the adjudicator is the oracle itself, so accuracy is
    perfect by construction and the comparison is about cost: every query re-reads
    the log and re-derives the relevant keys).
temporal_db: rule-based bitemporal store without justifications: per key, the record
    with the latest valid-time anchor <= t wins; retractions remove records; no error
    hypotheses, so every answer is 'established' or 'unknown'; derived values are
    computed at query time from current records.
"""
from __future__ import annotations

from typing import Any, Dict, List

from revise_stream import oracle_v1
from revise_stream.gold import gold_for, relevant_keys
from revise_stream.model import Query, Stream
from revise_stream.timeline import candidates_at


class LogQueryTime:
    def __init__(self, stream: Stream, policy: str = "P0c"):
        self.s = stream
        self.policy = policy
        self.cost = {"writes": 0, "reads": 0, "log_scanned": 0, "key_recomputes": 0}

    def answer(self, q: Query) -> Dict[str, Any]:
        from functools import partial
        s = self.s
        self.cost["reads"] += 1
        self.cost["log_scanned"] += sum(1 for o in s.observations if o.t_rep <= q.tau)
        # recompute from scratch: clear the per-key cache so the cost is real, not memoised
        for k in [k for k in s._cache if isinstance(k, tuple) and k[0] in ("kint", "prov")]:
            del s._cache[k]
        fn = partial(oracle_v1.interpretations, policy=self.policy)
        g = gold_for(s, q, fn)
        self.cost["key_recomputes"] += sum(1 for k in s._cache if isinstance(k, tuple) and k[0] == "kint")
        from eval.scorer import supporting_ids
        prov = g.get("provenance", []) if q.slot == "reported" else sorted(supporting_ids(s, q, g))
        return {"query_id": q.id, "status": g["status"], "assertion": g["assertion"],
                "alternatives": g.get("alternatives", []), "provenance": sorted(set(prov))}

    def _prov(self, q: Query, g) -> List[str]:
        s = self.s
        tau = q.tau_prime if q.slot == "belief_asof" else q.tau
        if q.slot == "yesno":
            p = q.prop
            if p["kind"] == "erroneous":
                return [p["obs"]] if any(o.id == p["obs"] for o in s.admitted(tau)) else []
            key = (p["entity"], p["attr"], p.get("ctx", ""))
            return [o.id for o in s.admitted_by_key(tau).get(key, [])]
        keys = relevant_keys(s, tau, q.entity, q.attr, q.ctx, oracle_v1.interpretations)
        ids = []
        vals = set()
        a = g.get("assertion")
        vals |= set(a) if isinstance(a, list) else ({a} if a is not None else set())
        for alt in g.get("alternatives", []):
            vals |= set(alt) if isinstance(alt, list) else ({alt} if alt is not None else set())
        for k in keys:
            for o in s.admitted_by_key(tau).get(k, []):
                if s.attributes[q.attr].derived or o.value in vals or g["status"] != "established":
                    ids.append(o.id)
        return ids


class TemporalDB:
    def __init__(self, stream: Stream):
        self.s = stream
        self.cost = {"writes": 0, "reads": 0}

    def _record(self, key, tau: int, t: int):
        """Latest admitted record with anchor <= t (valid-time aware), else None."""
        obs = [o for o in self.s.admitted_by_key(tau).get(key, []) if o.anchor <= t]
        if not obs:
            return None
        return max(obs, key=lambda o: (o.anchor, o.t_rep, o.id))

    def _value(self, key, tau: int, t: int):
        spec = self.s.attributes[key[1]]
        if spec.derived:
            # evaluate rules with a provider that returns the single committed value per key
            def prov(k, tt):
                r = self._record(k, tau, tt)
                if r is None:
                    return {frozenset()}
                return {frozenset([r.value])} if self.s.attributes[k[1]].cardinality == "single" else {frozenset(
                    o.value for o in self.s.admitted_by_key(tau).get(k, []) if o.anchor <= tt)}
            cands = candidates_at(self.s, prov, key, t)
            c = next(iter(cands)) if len(cands) == 1 else max(cands, key=len)
            return (next(iter(c)) if c else None) if spec.cardinality == "single" else sorted(c, key=str), []
        r = self._record(key, tau, t)
        if r is None:
            return None, []
        if spec.cardinality == "multi":
            vals = sorted({o.value for o in self.s.admitted_by_key(tau).get(key, []) if o.anchor <= t}, key=str)
            return vals, [o.id for o in self.s.admitted_by_key(tau).get(key, []) if o.anchor <= t]
        return r.value, [r.id]

    def answer(self, q: Query) -> Dict[str, Any]:
        self.cost["reads"] += 1
        s = self.s

        def est(v, prov):
            if v is None or v == []:
                return {"query_id": q.id, "status": "unknown", "assertion": None, "alternatives": [], "provenance": []}
            return {"query_id": q.id, "status": "established", "assertion": v, "alternatives": [], "provenance": sorted(set(prov))}

        if q.slot == "reported":
            rep: Dict[str, List[str]] = {}
            for o in s.admitted_by_key(q.tau).get((q.entity, q.attr, q.ctx), []):
                rep.setdefault(str(o.value), []).append(o.id)
            return {"query_id": q.id, "status": "established", "assertion": {k: sorted(v) for k, v in sorted(rep.items())},
                    "alternatives": [], "provenance": sorted(x for v in rep.values() for x in v)}
        if q.slot == "belief_asof":
            v, p = self._value((q.entity, q.attr, q.ctx), q.tau_prime, q.tau_prime)
            return est(v, p)
        if q.slot in ("current", "downstream", "asof"):
            t = q.t if q.t is not None else q.tau
            v, p = self._value((q.entity, q.attr, q.ctx), q.tau, t)
            return est(v, p)
        p = q.prop
        if p["kind"] == "erroneous":
            return {"query_id": q.id, "status": "established", "assertion": False, "alternatives": [], "provenance": [p["obs"]]}
        key = (p["entity"], p["attr"], p.get("ctx", ""))
        if p["kind"] == "changed":
            obs = sorted(s.admitted_by_key(q.tau).get(key, []), key=lambda o: (o.anchor, o.t_rep))
            vals = [o.value for o in obs]
            ok = p["from"] in vals and p["to"] in vals and vals.index(p["from"]) < len(vals) - 1 - vals[::-1].index(p["to"])
            return {"query_id": q.id, "status": "established", "assertion": bool(ok), "alternatives": [], "provenance": [o.id for o in obs]}
        v, pr = self._value(key, q.tau, p.get("t", q.tau))
        held = (p["value"] in v) if isinstance(v, list) else (v == p["value"])
        return {"query_id": q.id, "status": "established", "assertion": bool(held), "alternatives": [], "provenance": pr}
