"""Gold derivation from interpretations (SEMANTICS §9). Shared by both oracles."""
from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet, List, Set, Tuple

from .model import Query, Stream
from .timeline import Key, candidates_at, observed_candidates

InterpFn = Callable[..., Set]


def _candidate_values(stream: Stream, tau: int, key: Key, interp_fn: InterpFn) -> Set:
    """Union of values ever asserted on an observed key (over-approximation of the
    values any interpretation can bind), used only to bound relevant keys."""
    return {o.value for o in stream.admitted_by_key(tau).get(key, [])}


def relevant_keys(stream: Stream, tau: int, entity: str, attr: str, ctx: str, interp_fn: InterpFn, _depth: int = 0) -> Set[Key]:
    """Keys whose interpretations can influence (entity, attr) at belief time tau."""
    spec = stream.attributes[attr]
    if not spec.derived:
        return {(entity, attr, ctx)}
    if _depth > 8:
        raise RecursionError("rule recursion too deep")
    keys: Set[Key] = set()
    for r in stream.rules:
        if r.head[0] != attr:
            continue
        bound = {r.head[1]: {entity}}
        for (la, lx, ly) in r.body + r.exceptions:
            isv = lambda z: isinstance(z, str) and z.startswith("?")
            xs = bound.get(lx, set(stream.entities) if isv(lx) else {lx})
            vals: Set = set()
            for x in xs:
                keys |= relevant_keys(stream, tau, x, la, "", interp_fn, _depth + 1)
                vals |= _candidate_values(stream, tau, (x, la, ""), interp_fn) if not stream.attributes[la].derived else set(stream.entities)
            if isv(ly):
                bound[ly] = bound.get(ly, set()) | vals
    return keys


def _tl_dict(interp) -> Dict[Key, Tuple]:
    return dict(interp[1])


def _norm_cands(stream: Stream, attr: str, cands: Set[FrozenSet]) -> List[Any]:
    """Canonical JSON form of alternatives: scalars (or null) for single-valued keys,
    sorted lists for multi-valued keys."""
    spec = stream.attributes[attr]
    out = []
    for c in cands:
        if spec.cardinality == "single":
            out.append(next(iter(c)) if c else None)
        else:
            out.append(sorted(c, key=str))
    return sorted(out, key=lambda x: (x is None, str(x)))


def key_provider(stream: Stream, tau: int, interp_fn: InterpFn):
    """Provider: union over a key's own interpretations of its candidate value-sets.
    Cached per (tau, key, t) on the stream."""
    def prov(key: Key, t: int) -> Set[FrozenSet]:
        ck = ("prov", tau, key, t, getattr(interp_fn, "__module__", ""), getattr(interp_fn, "keywords", None) and str(interp_fn.keywords))
        if ck not in stream._cache:
            cands: Set[FrozenSet] = set()
            for it in interp_fn(stream, tau, keys={key}):
                cands |= observed_candidates(stream, dict(it[1]).get(key, ()), stream.attributes[key[1]], t)
            stream._cache[ck] = cands
        return stream._cache[ck]
    return prov


def support_ids(stream: Stream, tau: int, key: Key, t: int, interp_fn: InterpFn, answer_values=None) -> Set[str]:
    """Observation ids on an oracle justification path for `key` at valid time t:
    for an observed key, admitted assertions whose value is a candidate (or in
    `answer_values` when given); for a derived key, admitted assertions that assert a
    (key, value) binding used on some derivation path yielding a candidate value."""
    prov = key_provider(stream, tau, interp_fn)
    trace: list = []
    cands = candidates_at(stream, prov, key, t, trace=trace)
    wanted = set(answer_values) if answer_values is not None else {v for S in cands for v in S}
    spec = stream.attributes[key[1]]
    adm = stream.admitted_by_key(tau)
    if not spec.derived:
        return {o.id for o in adm.get(key, []) if o.value in wanted}
    pairs = set()
    for (k, v, used) in trace:
        if k == key and v in wanted:
            pairs |= used
    return {o.id for (k, v) in pairs for o in adm.get(k, []) if o.value == v}


def _value_gold(stream: Stream, prov, key: Key, t: int) -> Dict[str, Any]:
    cands = candidates_at(stream, prov, key, t)
    alts = _norm_cands(stream, key[1], cands)
    if not alts or (len(alts) == 1 and alts[0] is None):
        return {"status": "unknown", "assertion": None, "alternatives": []}
    if len(alts) == 1:
        return {"status": "established", "assertion": alts[0], "alternatives": []}
    return {"status": "unresolved", "assertion": None, "alternatives": alts}


def _yesno_gold(truths: List[bool]) -> Dict[str, Any]:
    if truths and all(truths):
        return {"status": "established", "assertion": True, "alternatives": []}
    if truths and not any(truths):
        return {"status": "established", "assertion": False, "alternatives": []}
    if not truths:
        return {"status": "unknown", "assertion": None, "alternatives": []}
    return {"status": "possible", "assertion": True, "alternatives": []}


def _changed(tl: Tuple, v1, v2) -> bool:
    """A run of v1 that ends (not INF) followed later by a run of v2."""
    segs = list(tl)
    for s1 in segs:
        if s1.value != v1 or s1.end_hi == float("inf"):
            continue
        for s2 in segs:
            if s2.value == v2 and s2.start >= s1.end_lo and s2.start > s1.start:
                return True
    return False


def gold_for(stream: Stream, q: Query, interp_fn: InterpFn) -> Dict[str, Any]:
    tau = q.tau
    if q.slot == "reported":
        obs = [o for o in stream.admitted(tau) if o.key == (q.entity, q.attr, q.ctx)]
        rep: Dict[str, List[str]] = {}
        for o in obs:
            rep.setdefault(str(o.value), []).append(o.id)
        return {"status": "established", "assertion": {k: sorted(v) for k, v in sorted(rep.items())},
                "alternatives": [], "provenance": sorted(o.id for o in obs)}
    if q.slot == "belief_asof":
        prov = key_provider(stream, q.tau_prime, interp_fn)
        return _value_gold(stream, prov, (q.entity, q.attr, q.ctx), q.tau_prime)
    prov = key_provider(stream, tau, interp_fn)
    if q.slot in ("current", "downstream"):
        t = q.t if q.t is not None else tau
        return _value_gold(stream, prov, (q.entity, q.attr, q.ctx), t)
    if q.slot == "asof":
        return _value_gold(stream, prov, (q.entity, q.attr, q.ctx), q.t)
    if q.slot == "yesno":
        p = q.prop
        truths: List[bool] = []
        if p["kind"] == "erroneous":
            adm = {o.id: o for o in stream.admitted(tau)}
            if p["obs"] not in adm:
                return _yesno_gold([])   # withdrawn/retracted/not yet reported: no admitted evidence bears on it
            key = adm[p["obs"]].key
            truths = [p["obs"] in it[0] for it in interp_fn(stream, tau, keys={key})]
        elif p["kind"] == "changed":
            key = (p["entity"], p["attr"], p.get("ctx", ""))
            truths = [_changed(dict(it[1]).get(key, ()), p["from"], p["to"]) for it in interp_fn(stream, tau, keys={key})]
        elif p["kind"] == "holds":
            t = p.get("t", tau)
            for c in candidates_at(stream, prov, (p["entity"], p["attr"], p.get("ctx", "")), t):
                truths.append(p["value"] in c)
        else:
            raise ValueError(p["kind"])
        return _yesno_gold(truths)
    raise ValueError(q.slot)


def warranted(stream: Stream, q: Query, interp_fn: InterpFn) -> bool:
    """§9: a downstream/current query at tau is a warranted-retraction consequence iff
    its gold is established at tau and differs from its gold at tau-1."""
    if q.slot not in ("downstream", "current", "asof"):
        return False
    now = gold_for(stream, q, interp_fn)
    if now["status"] != "established":
        return False
    prev_q = Query(**{**q.__dict__, "tau": q.tau - 1})
    before = gold_for(stream, prev_q, interp_fn)
    return (before["status"], before["assertion"]) != (now["status"], now["assertion"])


def all_gold(stream: Stream, interp_fn: InterpFn) -> Dict[str, Dict[str, Any]]:
    out = {}
    for q in stream.queries:
        g = gold_for(stream, q, interp_fn)
        g["warranted"] = warranted(stream, q, interp_fn) if "retraction_consequence" in q.tags else False
        g["resolvable"] = g["status"] in ("established",)
        out[q.id] = g
    return out
