"""PALIMPSEST support model (plan §3.2, RQ3): the probability that a candidate value is
true for its interval, estimated from the admitted evidence only.

Defined meaning. For key k at belief time tau, each admitted assertion of value v is
evidence. Evidence is grouped by ORIGIN (copies from the same origin count once), each
origin contributes log-odds lo(class) learned (or declared) per reliability class,
discounted for staleness on changeable attributes (a report of a volatile attribute
anchored d days before the latest report on that key counts lo * decay(d)), capped by
min(provenance, content): a report whose content is contradicted by a declared
correction cue from a higher-rank origin contributes at most the correction's weight.
Operator cues adjust the prior: a change cue is positive evidence for the new value
and ends support for the previous one; a correction cue transfers the target's weight.

support(v) = sigmoid(sum_{origins for v} w  -  sum_{origins for v' != v} w  +  b)

with b the class-prior of 'no competing evidence'. Support is produced for every
candidate value the oracle lists (so it is evaluated exactly on the alternatives the
justified-belief layer keeps open) and for the committed answer of commit-style
systems. Priors can be fitted from verified outcomes (hidden world truth of training
streams) by one-dimensional logistic calibration per class; the fitted priors are the
'learned source prior'. Source identities are never used, only classes and origins.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from revise_stream.model import Observation, Stream

Key = Tuple[str, str, str]
DEFAULT_LOGODDS = {"trusted": 2.2, "standard": 1.2, "low": 0.3}
DEFAULT_BIAS = 0.5


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class SupportModel:
    def __init__(self, logodds: Optional[Dict[str, float]] = None, bias: float = DEFAULT_BIAS,
                 half_life_days: float = 20.0, origin_grouping: bool = True, use_cues: bool = True):
        self.lo = dict(logodds or DEFAULT_LOGODDS)
        self.bias = bias
        self.half_life = half_life_days
        self.origin_grouping = origin_grouping
        self.use_cues = use_cues

    def evidence(self, stream: Stream, key: Key, tau: int, t: Optional[int] = None) -> Dict[object, float]:
        """Net evidence weight per candidate value from admitted observations on key."""
        obs = stream.admitted_by_key(tau).get(key, [])
        spec = stream.attributes[key[1]]
        if not obs:
            return {}
        latest = max(o.anchor for o in obs)
        per_origin: Dict[Tuple[str, object], float] = defaultdict(float)
        corrected = {o.op_of for o in obs if o.op_cue == "correction"}
        for o in obs:
            cls = stream.sources[o.source].cls
            w = self.lo.get(cls, 0.5)
            if spec.changeable and self.half_life > 0:
                d = max(0, latest - o.anchor)
                w *= 0.5 ** (d / self.half_life)
            if self.use_cues:
                if o.op_cue == "change":
                    w *= 1.25
                if o.id in corrected:
                    # min(provenance, content): a corrected report's weight is capped by the
                    # weight of the correction that targets it
                    corr = [x for x in obs if x.op_cue == "correction" and x.op_of == o.id]
                    cap = max(self.lo.get(stream.sources[x.source].cls, 0.5) for x in corr)
                    w = min(w, 0.5 * cap)
            origin = stream.sources[o.source].origin if self.origin_grouping else o.source
            per_origin[(origin, o.value)] = max(per_origin[(origin, o.value)], w)
        by_value: Dict[object, float] = defaultdict(float)
        for (origin, v), w in per_origin.items():
            by_value[v] += w
        return dict(by_value)

    def support(self, stream: Stream, key: Key, tau: int, candidates: List[object], t: Optional[int] = None) -> Dict[object, float]:
        ev = self.evidence(stream, key, tau, t)
        out = {}
        total = sum(ev.values())
        for v in candidates:
            pro = ev.get(v, 0.0)
            con = total - pro
            out[v] = _sigmoid(pro - con + (self.bias if con == 0 else 0.0))
        return out


def fit_class_priors(records: List[Tuple[str, bool]]) -> Dict[str, float]:
    """Learned source prior: per class, log-odds of a report being true, from verified
    outcomes (class, was_true) — with Laplace smoothing."""
    cnt: Dict[str, List[int]] = defaultdict(lambda: [1, 1])
    for cls, ok in records:
        cnt[cls][0 if ok else 1] += 1
    return {cls: math.log(a / b) for cls, (a, b) in cnt.items()}


# ---------- calibration metrics ----------
def brier(pairs: List[Tuple[float, int]]) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / max(1, len(pairs))


def ece(pairs: List[Tuple[float, int]], bins: int = 15) -> float:
    """Expected calibration error with equal-mass bins."""
    if not pairs:
        return float("nan")
    ps = sorted(pairs)
    n = len(ps)
    tot = 0.0
    for b in range(bins):
        chunk = ps[b * n // bins:(b + 1) * n // bins]
        if not chunk:
            continue
        conf = sum(p for p, _ in chunk) / len(chunk)
        acc = sum(y for _, y in chunk) / len(chunk)
        tot += len(chunk) / n * abs(conf - acc)
    return tot


def aurc(pairs: List[Tuple[float, int]]) -> float:
    """Area under the risk–coverage curve (lower is better): answer in order of
    decreasing confidence; risk at coverage c = error rate among the covered."""
    if not pairs:
        return float("nan")
    ps = sorted(pairs, key=lambda x: -x[0])
    err = 0
    area = 0.0
    for i, (_, y) in enumerate(ps, start=1):
        err += 1 - y
        area += err / i
    return area / len(ps)
