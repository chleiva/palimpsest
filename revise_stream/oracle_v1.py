"""Oracle v1: constructive, per-key implementation of SEMANTICS §6–7.

Admissibility conditions are local to a key (disputes, corrections, change cues
and contradictions never cross keys), so the set of interpretations is the
product over keys of per-key interpretation sets. Each per-key set is built by
walking subsets of accepted (TRUE) assertions as bitmasks and constructing
timelines with an anchor sweep. Written separately from oracle_v2 so that the
Phase 0 gate compares two derivations of the same semantics.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Dict, FrozenSet, List, Set, Tuple

from .model import INF, Observation, Stream
from .timeline import Key, Segment, Timeline


def _shielded(o: Observation, p: Observation, policy: str) -> bool:
    """Cue resolution (policy P0c / P0cc): a report carrying an explicit operator cue is
    not disputed by competitors anchored strictly earlier than itself — the cue identifies the
    revision operator, so the earlier value is explained, not contested. Later
    competitors still dispute it."""
    cues = {"P0c": ("change",), "P0cSU": ("change",), "P0cc": ("change", "correction")}.get(policy, ())
    return o.op_cue in cues and p.anchor < o.anchor


def _self_superseded(stream: Stream, o: Observation, T: List[Observation], spec) -> bool:
    """A-SU (PREREGISTRATION Addendum A, variant P0cSU): on a single-valued changeable key a report
    o may not be labelled ERR when every accepted competitor of o is a strictly-earlier report from
    o's own origin and no accepted correction targets o — the source's later value supersedes its own
    earlier value instead of disputing it."""
    if spec.cardinality != "single" or not spec.changeable:
        return False
    if any(p.op_cue == "correction" and p.op_of == o.id for p in T):
        return False
    comp = [p for p in T if p.value != o.value]
    if not comp:
        return False
    og = stream.sources[o.source].origin
    return all(stream.sources[p.source].origin == og and p.anchor < o.anchor for p in comp)


def _key_interps(stream: Stream, key: Key, obs: List[Observation], policy: str = "P0c", tau: int = 0, relax: int = 0) -> Set[Tuple[FrozenSet[str], Timeline]]:
    spec = stream.attributes[key[1]]
    n = len(obs)
    out: Set[Tuple[FrozenSet[str], Timeline]] = set()
    for mask in range(1 << n):
        T = [obs[i] for i in range(n) if mask >> i & 1]
        R = [obs[i] for i in range(n) if not mask >> i & 1]
        tv = {o.value for o in T}
        tid = {o.id for o in T}
        ok = True
        # errors must be allowed and explained by an accepted competitor or correction;
        # under P1 a competitor only counts if its class rank is >= the error's, or it is corroborated
        for o in R:
            if not spec.error_allowed:
                ok = False; break
            comp = [p for p in T if p.value != o.value]
            comp = [p for p in comp if not _shielded(o, p, policy)]
            if policy == "P1":
                comp = [p for p in comp if stream.rank(p) >= stream.rank(o) or stream.corroborated(p, tau)]
            if not ((comp and spec.competing_values) or any(p.op_cue == "correction" and p.op_of == o.id for p in T)):
                ok = False; break
            if policy == "P0cSU" and _self_superseded(stream, o, T, spec):
                ok = False; break
        if not ok:
            continue
        # an accepted correction rejects its target
        if any(p.op_cue == "correction" and p.op_of in tid for p in T):
            continue
        # an accepted change-from presupposes the previous value: if any earlier report of
        # it exists, at least one must be accepted
        for p in T:
            if relax == 0 and p.op_cue == "change" and p.op_from is not None:
                prev = [q for q in obs if q.value == p.op_from and q.anchor < p.anchor and q.id != p.id]
                if prev and not any(q.id in tid for q in prev):
                    ok = False; break
        if not ok:
            continue
        # consistency among accepted reports
        if spec.cardinality == "single":
            if not spec.changeable and len(tv) > 1:
                continue
            anchors: Dict[int, Set] = defaultdict(set)
            for o in T:
                anchors[o.anchor].add(o.value)
            if any(len(vs) > 1 for vs in anchors.values()):
                continue
        err = frozenset(o.id for o in R)
        for tl in _sweep(spec, T):
            out.add((err, tl))
    return out


def _sweep(spec, T: List[Observation]) -> List[Timeline]:
    """Anchor sweep: build maximal same-value runs, then segments per §7."""
    if not T:
        return [()]
    events = sorted(((o.anchor, str(o.value), o.value, o) for o in T), key=lambda x: (x[0], x[1]))
    runs: List[Tuple[object, int, int]] = []        # (value, first, last)
    for a, _, v, o in events:
        if runs and runs[-1][0] == v:
            runs[-1] = (v, runs[-1][1], a)
        else:
            runs.append((v, a, a))
    if spec.cardinality == "single":
        segs = []
        for i, (v, first, last) in enumerate(runs):
            if i + 1 < len(runs):
                segs.append(Segment(v, runs[i - 1][2] if i else first, first, last, runs[i + 1][1]))
            else:
                segs.append(Segment(v, runs[i - 1][2] if i else first, first, INF, INF))
        return [tuple(sorted(segs))]
    # multi-valued: each run followed by another run chooses CONT or ENDED, unless a
    # change-from cue forces ENDED on the run of the previous value
    forced = set()
    for o in T:
        if o.op_cue == "change" and o.op_from is not None:
            for i, (v, first, last) in enumerate(runs[:-1]):
                if v == o.op_from and last < o.anchor:
                    forced.add(i)
    slots = [i for i in range(len(runs) - 1) if i not in forced]
    if not spec.changeable:
        slots, forced = [], set()
    tls = []
    for choice in product(["CONT", "ENDED"], repeat=len(slots)):
        lab = {i: c for i, c in zip(slots, choice)}
        lab.update({i: "ENDED" for i in forced})
        segs = []
        for i, (v, first, last) in enumerate(runs):
            if lab.get(i) == "ENDED":
                segs.append(Segment(v, first, first, last, runs[i + 1][1]))
            else:
                segs.append(Segment(v, first, first, INF, INF))
        tls.append(tuple(sorted(segs)))
    return tls


def key_interpretations(stream: Stream, tau: int, key: Key, policy: str = "P0c"):
    """Cached per-key interpretation set (keys are independent under SEMANTICS §6)."""
    ck = ("kint", tau, key, policy)
    if ck not in stream._cache:
        obs = stream.admitted_by_key(tau).get(key, [])
        res = sorted(_key_interps(stream, key, obs, policy, tau), key=repr) if obs else [(frozenset(), ())]
        # Totality ladder (SEMANTICS §6, "relaxation"): the admissibility conditions can be
        # jointly unsatisfiable on noisy or adversarial streams (e.g. an unsatisfiable
        # change presupposition under P1). Each step is recorded in stream._cache['_relax'].
        if not res and obs:
            for level, (pol, rl) in enumerate(((policy, 1), ("P0", 1)), start=1):
                res = sorted(_key_interps(stream, key, obs, pol, tau, relax=rl), key=repr)
                if res:
                    break
            else:
                level = 3
                res = [(frozenset(o.id for o in obs), ())]      # everything rejected: the key is unknown
            stream._cache.setdefault("_relax", []).append((tau, key, level))
        stream._cache[ck] = res
    return stream._cache[ck]


def interpretations(stream: Stream, tau: int, policy: str = "P0c", keys=None):
    """Product of per-key interpretation sets. With `keys`, only those keys are
    combined (gold for a query needs only the keys it can depend on; see gold.relevant_keys)."""
    keys = sorted(stream.admitted_by_key(tau)) if keys is None else sorted(keys)
    per_key = [key_interpretations(stream, tau, k, policy) for k in keys]
    result = set()
    for combo in product(*per_key):
        err = frozenset().union(*[c[0] for c in combo]) if combo else frozenset()
        tls = tuple(sorted((k, c[1]) for k, c in zip(keys, combo) if c[1]))
        result.add((err, tls))
    return result
