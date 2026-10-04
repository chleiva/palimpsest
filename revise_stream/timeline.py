"""Shared timeline representation, value lookup and rule engine (SEMANTICS §7).

This module is shared by both oracle implementations. What the two oracles
implement *independently* is admissibility (§6) and the construction of
timelines from label assignments; what they share is the meaning of a timeline
once built, the rule engine, and the status derivation in gold.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from .model import INF, AttributeSpec, Rule, Stream

Key = Tuple[str, str, str]


@dataclass(frozen=True, order=True)
class Segment:
    """A value run. It begins at an unknown change point c_in in (start_lo, start]
    (start_lo == start means the start is the anchor itself), holds definitely on
    [start, end_lo], and ends at an unknown change point c_out in (end_lo, end_hi]
    (end_lo == end_hi == INF means it persists forever)."""
    value: object
    start_lo: float
    start: int
    end_lo: float
    end_hi: float

    def covers(self, t: int) -> Optional[bool]:
        """True = definitely covers t; False = definitely not; None = ambiguous."""
        if t < self.start:
            return None if self.start_lo < t else False
        if t <= self.end_lo:
            return True
        if t < self.end_hi:
            return None
        return False


Timeline = Tuple[Segment, ...]          # one key
Interp = Tuple[FrozenSet[str], Dict[Key, Timeline]]   # (ERR observation ids, timelines)


def observed_candidates(stream: Stream, tl: Timeline, spec: AttributeSpec, t: int) -> Set[FrozenSet]:
    """Candidate value-sets for one observed key at valid time t under one timeline."""
    definite, ambiguous = set(), set()
    for seg in tl:
        c = seg.covers(t)
        if c is True:
            definite.add(seg.value)
        elif c is None:
            ambiguous.add(seg.value)
    ambiguous -= definite
    if spec.cardinality == "single":
        # at most one value holds; inside a gap the value is v_prev or v_next, never both
        if definite:
            return {frozenset([v]) for v in definite}
        if ambiguous:
            return {frozenset([v]) for v in ambiguous}
        return {frozenset()}
    out = set()
    amb = sorted(ambiguous, key=str)
    for mask in product([False, True], repeat=len(amb)):
        s = set(definite) | {v for v, m in zip(amb, mask) if m}
        out.add(frozenset(s))
    return out


def timeline_provider(stream: Stream, timelines: Dict[Key, Timeline]):
    """Provider over one interpretation's timelines."""
    def prov(key: Key, t: int) -> Set[FrozenSet]:
        return observed_candidates(stream, timelines.get(key, ()), stream.attributes[key[1]], t)
    return prov


def candidates_at(stream: Stream, source, key: Key, t: int, _depth: int = 0, trace: Optional[list] = None) -> Set[FrozenSet]:
    """Set of candidate value-sets for `key` at valid time t. `source` is either a
    timelines dict (one interpretation) or a provider callable (key, t) -> candidate
    sets for observed keys (e.g. the union over a key's interpretations: keys are
    independent, so the union over the product of interpretations equals the rule
    engine's branching over per-key unions, provided a key is referenced at most once
    per derivation path, which holds for the declared rule sets)."""
    provider = source if callable(source) else timeline_provider(stream, source)
    e, a, ctx = key
    if stream.attributes[a].derived:
        return _derive(stream, provider, key, t, _depth, trace)
    cands = provider(key, t)
    if trace is not None:
        for S in cands:
            for v in S:
                trace.append((key, v, frozenset()))      # observed binding, no path context
    return cands


def _derive(stream: Stream, timelines, key: Key, t: int, depth: int, trace: Optional[list] = None) -> Set[FrozenSet]:
    if depth > 8:
        raise RecursionError("rule recursion too deep")
    e, a, ctx = key
    worlds: Set[FrozenSet] = {frozenset()}
    rules = [r for r in stream.rules if r.head[0] == a]
    if not rules:
        return worlds
    for r in rules:
        rw = _eval_rule(stream, timelines, r, e, t, depth, trace)
        worlds = {w1 | w2 for w1 in worlds for w2 in rw}
    return worlds


def _eval_rule(stream, timelines, r: Rule, e: str, t: int, depth: int, trace: Optional[list] = None) -> Set[FrozenSet]:
    """Evaluate one rule for head entity e at time t. With `trace`, every derivation
    path that yields a head value v appends (head_key, v, frozenset of (key, value)
    bindings used along the path, exceptions included) — the justification path."""
    head_attr, head_e, head_v = r.head
    binding = {head_e: e}

    def rec(lits: Tuple, b: Dict[str, object], used: FrozenSet) -> Set[FrozenSet]:
        if not lits:
            v = b.get(head_v)
            if v is None:
                return {frozenset()}
            # exceptions: evaluated per world; an exception that holds blocks the rule
            outs = {frozenset([v])}
            exc_used = set()
            for (xa, xe, xv) in r.exceptions:
                ent = b.get(xe, xe)
                exc = candidates_at(stream, timelines, (ent, xa, ""), t, depth + 1)
                new = set()
                for w in outs:
                    for S in exc:
                        new.add(frozenset() if xv in S else w)
                        for y in S:
                            exc_used.add(((ent, xa, ""), y))
                outs = new
            if trace is not None:
                for w in outs:
                    for hv in w:
                        trace.append(((e, head_attr, ""), hv, used | frozenset(exc_used)))
            return outs
        (la, lx, ly), rest = lits[0], lits[1:]
        xs = [b[lx]] if lx in b else (stream.entities if lx.startswith("?") else [lx])
        worlds_out: Set[FrozenSet] = set()
        for x in xs:
            b1 = dict(b, **{lx: x})
            sub_trace = [] if trace is not None else None
            cands = candidates_at(stream, timelines, (x, la, ""), t, depth + 1, sub_trace)
            for S in cands:                      # each candidate set is one world
                ys = [y for y in S if (ly not in b1 or b1[ly] == y)] if ly.startswith("?") else ([ly] if ly in S else [])
                if not ys:
                    worlds_out.add(frozenset())
                    continue
                # multiple bindings in one world: union of head values
                combo: Set[FrozenSet] = {frozenset()}
                for y in ys:
                    used1 = used | {((x, la, ""), y)}
                    if sub_trace:   # a derived body literal: fold its own paths in
                        for (k2, v2, u2) in sub_trace:
                            if k2 == (x, la, "") and v2 == y:
                                used1 = used1 | u2
                    sub = rec(rest, dict(b1, **{ly: y}), used1)
                    combo = {c | s for c in combo for s in sub}
                worlds_out |= combo
        return worlds_out

    return rec(r.body, binding, frozenset())


def runs_from_anchors(items: Iterable[Tuple[object, int]]) -> List[Tuple[object, int, int]]:
    """Coalesce (value, anchor) pairs sorted by anchor into maximal same-value runs:
    returns [(value, first_anchor, last_anchor), ...]. Raises on two different values
    at the same anchor (a contradiction for single-valued keys; callers decide)."""
    runs: List[List] = []
    for v, a in sorted(items, key=lambda x: (x[1], str(x[0]))):
        if runs and runs[-1][0] == v:
            runs[-1][2] = a
        else:
            runs.append([v, a, a])
    return [tuple(r) for r in runs]
