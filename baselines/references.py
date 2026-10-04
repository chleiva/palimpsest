"""Reference behaviours (plan §3.3): always-abstain and always-commit. Not competitors;
they bound the two failure modes and are part of the Phase 1 gate."""
from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List

from revise_stream.model import Query, Stream


def _reported(stream: Stream, q: Query):
    tau = q.tau_prime if q.slot == "belief_asof" else q.tau
    key = (q.entity, q.attr, q.ctx)
    return [o for o in stream.admitted(tau) if o.key == key]


def _body_keys_reported(stream: Stream, q: Query):
    """For derived attributes: admitted assertions on body keys (always-commit chains the latest)."""
    tau = q.tau
    out = []
    for r in stream.rules:
        if r.head[0] == q.attr:
            for (a, _, _) in r.body:
                out += [o for o in stream.admitted(tau) if o.attr == a]
    return out


def always_abstain(stream: Stream, q: Query) -> Dict[str, Any]:
    if q.slot == "yesno":
        return {"query_id": q.id, "status": "possible", "assertion": True, "alternatives": [], "provenance": []}
    if q.slot == "reported":
        rep: Dict[str, List[str]] = {}
        for o in _reported(stream, q):
            rep.setdefault(str(o.value), []).append(o.id)
        return {"query_id": q.id, "status": "established", "assertion": {k: sorted(v) for k, v in rep.items()},
                "alternatives": [], "provenance": [o.id for o in _reported(stream, q)]}
    obs = _reported(stream, q) if not stream.attributes[q.attr].derived else _body_keys_reported(stream, q)
    vals = sorted({o.value for o in obs}, key=str)
    if not vals:
        return {"query_id": q.id, "status": "unknown", "assertion": None, "alternatives": [], "provenance": []}
    if stream.attributes[q.attr].cardinality == "multi":
        alts = [sorted(c, key=str) for n in range(1, len(vals) + 1) for c in combinations(vals, n)]
    else:
        alts = vals
    return {"query_id": q.id, "status": "unresolved", "assertion": None, "alternatives": alts,
            "provenance": [o.id for o in obs]}


def always_commit(stream: Stream, q: Query) -> Dict[str, Any]:
    """Last-write-wins: take the most recently reported value at face value."""
    if q.slot == "reported":
        return always_abstain(stream, q)
    if q.slot == "yesno":
        p = q.prop
        if p["kind"] == "erroneous":
            return {"query_id": q.id, "status": "established", "assertion": False, "alternatives": [], "provenance": [p["obs"]]}
        key = (p["entity"], p["attr"], p.get("ctx", ""))
        obs = sorted((o for o in stream.admitted(q.tau) if o.key == key), key=lambda o: (o.t_rep, o.id))
        if p["kind"] == "changed":
            vals = [o.value for o in obs]
            ok = p["to"] in vals and p["from"] in vals and vals.index(p["from"]) < len(vals) - 1 - vals[::-1].index(p["to"])
            return {"query_id": q.id, "status": "established", "assertion": bool(ok), "alternatives": [], "provenance": [o.id for o in obs]}
        latest = obs[-1].value if obs else None
        return {"query_id": q.id, "status": "established", "assertion": latest == p["value"], "alternatives": [],
                "provenance": [obs[-1].id] if obs else []}
    spec = stream.attributes[q.attr]
    if spec.derived:
        # chain the latest body values through the first matching rule, ignoring exceptions
        tau = q.tau
        for r in stream.rules:
            if r.head[0] != q.attr:
                continue
            b = {r.head[1]: q.entity}
            for (a, x, y) in r.body:
                ent = b.get(x)
                obs = sorted((o for o in stream.admitted(tau) if o.entity == ent and o.attr == a), key=lambda o: (o.t_rep, o.id))
                if not obs:
                    return {"query_id": q.id, "status": "unknown", "assertion": None, "alternatives": [], "provenance": []}
                b[y] = obs[-1].value
            v = b.get(r.head[2])
            return {"query_id": q.id, "status": "established", "assertion": v, "alternatives": [], "provenance": []}
    obs = sorted(_reported(stream, q), key=lambda o: (o.t_rep, o.id))
    if not obs:
        return {"query_id": q.id, "status": "unknown", "assertion": None, "alternatives": [], "provenance": []}
    v = obs[-1].value
    if spec.cardinality == "multi":
        v = [v]
    return {"query_id": q.id, "status": "established", "assertion": v, "alternatives": [], "provenance": [obs[-1].id]}
