"""Endpoints and uncertainty (plan §5 / PREREGISTRATION).

Per stream, from scored answers:
  warranted_acc        exact accuracy on warranted-retraction consequence queries on DOWNSTREAM
                       (derived) slots (primary endpoint: propagation through justifications)
  warranted_direct_acc same, on the retracted key itself (ordinary belief updating; secondary)
  reported_acc         observational slot, reported separately and excluded from the strata
  resolvable_acc       exact accuracy on established-gold queries
  unresolved_acc       exact accuracy on unresolved/possible-gold queries
  commit_rate          premature commitment rate on unresolved/possible-gold queries
  unsupported_prop     share of non-warranted event queries (downstream/current, tagged
                       retraction_consequence, gold not warranted) whose answer changed
                       between the 'pre' companion (tau-1) and the event query (tau)
  malformed_rate
  cost                 system-reported work units
Stream-level cluster bootstrap for means and paired differences.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from eval.scorer import norm


def _mean(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def stream_metrics(stream, answers: Dict[str, Dict[str, Any]], gold: Dict[str, Dict[str, Any]],
                   scores: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[float]]:
    byid = {q.id: q for q in stream.queries}
    pre = {(q.entity, q.attr, q.slot, q.tau): q.id for q in stream.queries if "pre" in q.tags}
    warr, warr_direct, res, unres, commit, malformed, unsup, reported = [], [], [], [], [], [], [], []
    slot_acc: Dict[str, List[int]] = {}
    for qid, g in gold.items():
        q = byid[qid]
        if "pre" in q.tags:
            continue
        sc = scores[qid]
        malformed.append(sc["malformed"])
        slot = q.slot if q.slot != "yesno" else "yesno_" + q.prop["kind"]
        slot_acc.setdefault(slot, []).append(sc["exact"])
        if q.slot == "reported":
            reported.append(sc["exact"])
            continue
        if g.get("warranted"):
            (warr if q.slot == "downstream" else warr_direct).append(sc["exact"])
        if g["status"] == "established":
            res.append(sc["exact"])
        elif g["status"] in ("unresolved", "possible"):
            unres.append(sc["exact"])
            commit.append(sc["committed"])
        if "event" in q.tags and q.slot in ("downstream", "current") and not g.get("warranted"):
            pid = pre.get((q.entity, q.attr, q.slot, q.tau - 1))
            if pid and pid in answers:
                a0, a1 = answers[pid], answers[qid]
                changed = (a0["status"], norm(a0.get("assertion")), norm(a0.get("alternatives"))) != \
                          (a1["status"], norm(a1.get("assertion")), norm(a1.get("alternatives")))
                # only count as unsupported if the gold itself did not change
                g0 = gold.get(pid)
                gold_changed = g0 is not None and (g0["status"], norm(g0["assertion"]), norm(g0["alternatives"])) != \
                               (g["status"], norm(g["assertion"]), norm(g["alternatives"]))
                if not gold_changed:
                    unsup.append(int(changed))
    return {"warranted_acc": _mean(warr), "warranted_direct_acc": _mean(warr_direct), "resolvable_acc": _mean(res),
            "unresolved_acc": _mean(unres), "commit_rate": _mean(commit), "unsupported_prop": _mean(unsup),
            "malformed_rate": _mean(malformed), "reported_acc": _mean(reported),
            "n_warranted": len(warr), "n_warranted_direct": len(warr_direct), "n_resolvable": len(res),
            "n_unresolved": len(unres), "n_unsup_pairs": len(unsup),
            "slot_acc": {k: _mean(v) for k, v in slot_acc.items()}}


def bootstrap_mean(values: Sequence[Optional[float]], n_boot: int = 10000, seed: int = 0) -> Tuple[float, float, float]:
    xs = [v for v in values if v is not None]
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    m = sum(xs) / len(xs)
    boots = []
    for _ in range(n_boot):
        samp = [xs[rng.randrange(len(xs))] for _ in xs]
        boots.append(sum(samp) / len(samp))
    boots.sort()
    return m, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]


def bootstrap_paired(a: Sequence[Optional[float]], b: Sequence[Optional[float]], n_boot: int = 10000, seed: int = 0):
    """Paired per-stream differences a - b with stream-level bootstrap CI."""
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    return bootstrap_mean(d, n_boot, seed), len(d)
