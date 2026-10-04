"""Oracle v2: brute-force reference implementation of SEMANTICS §6–7.

Enumerates every global TRUE/ERR labelling of the admitted assertions, filters by
the admissibility conditions stated one by one, then enumerates CONT/ENDED labels
for multi-valued runs and builds timelines by direct construction from the rules
in §7. Intended to be obviously correct, not fast.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Dict, FrozenSet, List, Set, Tuple

from .model import INF, Observation, Stream
from .timeline import Interp, Key, Segment, Timeline, runs_from_anchors


def _disputes(stream: Stream, o: Observation, p: Observation, policy: str = "P0c", tau: int = 0) -> bool:
    """p disputes o (so o may be hypothesised ERR). P0: any competing value. P1 (declared
    sensitivity variant): only if p's class rank >= o's, or p is corroborated from a
    second origin."""
    if not (o.key == p.key and o.id != p.id and o.value != p.value
            and stream.attributes[o.attr].competing_values):
        return False
    cues = {"P0c": ("change",), "P0cc": ("change", "correction")}.get(policy, ())
    if o.op_cue in cues and p.anchor < o.anchor:
        return False            # cue resolution: the cue explains the earlier value
    if policy == "P1":
        return stream.rank(p) >= stream.rank(o) or stream.corroborated(p, tau)
    return True


def _contradict(stream: Stream, o: Observation, p: Observation) -> bool:
    """§5 contradiction between two TRUE assertions (Phase 0 cues: none/since/at)."""
    if o.key != p.key or o.value == p.value:
        return False
    spec = stream.attributes[o.attr]
    if spec.cardinality == "multi":
        return False
    if not spec.changeable:
        return True
    # single, changeable: explicit 'at'/'since' cues with the same anchor contradict;
    # 'none' cues anchored at the same report time with different values contradict too
    return o.anchor == p.anchor


def _admissible(stream: Stream, obs: List[Observation], label: Dict[str, str], policy: str = "P0c", tau: int = 0) -> bool:
    true = [o for o in obs if label[o.id] == "TRUE"]
    by_id = {o.id: o for o in obs}
    # A-ERR
    for o in obs:
        if label[o.id] != "ERR":
            continue
        if not stream.attributes[o.attr].error_allowed:
            return False
        explained = any(_disputes(stream, o, p, policy, tau) for p in true) or any(
            p.op_cue == "correction" and p.op_of == o.id for p in true)
        if not explained:
            return False
    # A-CORR
    for p in true:
        if p.op_cue == "correction" and p.op_of in by_id and label[p.op_of] != "ERR":
            return False
    # A-CHG (with 'from'): if any earlier report of op_from exists, at least one must be TRUE
    for p in true:
        if p.op_cue == "change" and p.op_from is not None:
            earlier = [q for q in obs if q.key == p.key and q.value == p.op_from and q.anchor < p.anchor and q.id != p.id]
            if earlier and not any(label[q.id] == "TRUE" for q in earlier):
                return False
    # A-CONS / A-STABLE
    for i, o in enumerate(true):
        for p in true[i + 1:]:
            if _contradict(stream, o, p):
                return False
    return True


def _timelines(stream: Stream, true: List[Observation], cont: Dict[Tuple[Key, int], str]) -> Dict[Key, Timeline]:
    out: Dict[Key, Timeline] = {}
    by_key: Dict[Key, List[Observation]] = defaultdict(list)
    for o in true:
        by_key[o.key].append(o)
    for key, os_ in by_key.items():
        spec = stream.attributes[key[1]]
        runs = runs_from_anchors((o.value, o.anchor) for o in os_)
        segs: List[Segment] = []
        for i, (v, first, last) in enumerate(runs):
            nxt = runs[i + 1] if i + 1 < len(runs) else None
            if spec.cardinality == "single":
                start_lo = runs[i - 1][2] if i > 0 else first
                end_lo, end_hi = (last, nxt[1]) if nxt else (INF, INF)
                segs.append(Segment(v, start_lo, first, end_lo, end_hi))
            else:
                lab = cont.get((key, i), "CONT")
                if nxt and lab == "ENDED":
                    segs.append(Segment(v, first, first, last, nxt[1]))
                else:
                    segs.append(Segment(v, first, first, INF, INF))
        out[key] = tuple(sorted(segs))
    return out


def _forced_ended(stream: Stream, true: List[Observation], key: Key, runs) -> Set[int]:
    """A-CHG on multi keys: a TRUE change(from=v_prev) forces v_prev's latest earlier run ENDED."""
    forced = set()
    for p in true:
        if p.key == key and p.op_cue == "change" and p.op_from is not None:
            for i, (v, first, last) in enumerate(runs):
                if v == p.op_from and last < p.anchor and i + 1 < len(runs):
                    forced.add(i)
    return forced


def interpretations(stream: Stream, tau: int, policy: str = "P0c", keys=None) -> Set[Interp]:
    full = _interpretations(stream, tau, policy)
    if keys is None:
        return full
    keys = set(keys)
    ids = {o.id for o in stream.admitted(tau) if o.key in keys}
    return {(err & ids, tuple((k, tl) for k, tl in tls if k in keys)) for err, tls in full}


def _interpretations(stream: Stream, tau: int, policy: str = "P0c") -> Set[Interp]:
    obs = stream.admitted(tau)
    result: Set[Interp] = set()
    # same-anchor same-key different-value TRUE pairs on single keys are contradictions
    for labels in product(["TRUE", "ERR"], repeat=len(obs)):
        label = {o.id: l for o, l in zip(obs, labels)}
        if not _admissible(stream, obs, label, policy, tau):
            continue
        true = [o for o in obs if label[o.id] == "TRUE"]
        err = frozenset(o.id for o in obs if label[o.id] == "ERR")
        # CONT/ENDED choices for multi-valued runs that are followed by a different run
        choice_slots: List[Tuple[Key, int]] = []
        forced: Dict[Tuple[Key, int], str] = {}
        by_key: Dict[Key, List[Observation]] = defaultdict(list)
        for o in true:
            by_key[o.key].append(o)
        for key, os_ in by_key.items():
            if stream.attributes[key[1]].cardinality != "multi" or not stream.attributes[key[1]].changeable:
                continue
            runs = runs_from_anchors((o.value, o.anchor) for o in os_)
            fe = _forced_ended(stream, true, key, runs)
            for i in range(len(runs) - 1):
                if i in fe:
                    forced[(key, i)] = "ENDED"
                else:
                    choice_slots.append((key, i))
        for choice in product(["CONT", "ENDED"], repeat=len(choice_slots)):
            cont = dict(forced)
            cont.update({slot: c for slot, c in zip(choice_slots, choice)})
            tls = _timelines(stream, true, cont)
            result.add((err, _freeze(tls)))
    return result


def _freeze(tls: Dict[Key, Timeline]):
    return tuple(sorted(tls.items()))
