"""PALIMPSEST core, structured setting (Phase 1; no LLM).

A write-time belief store. Every observed key holds an append-only list of versions
(belief time, admitted observation ids, interpretation set). Every derived belief
(entity, derived attribute) holds versions that *pin* the key versions it was
justified by. Answers are read from the versions in force at the query's belief
time, so bitemporal questions are lookups, not recomputation.

Variants (plan §4 ablations / Phase 1 gate):
  propagation="on"   (default) a retraction or withdrawal on key K refreshes every
                     derived record that depends on K (justification propagation).
  propagation="off"  a retraction updates K only; derived records keep their pinned
                     versions until an ordinary assertion on a body key refreshes
                     them (ordinary belief updating without retraction propagation).
  commit=True        forced commitment: each key keeps a single interpretation (the
                     admissible one with fewest ERR labels, ties -> ENDED over CONT).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from revise_stream import oracle_v1
from revise_stream.gold import _changed, _value_gold, _yesno_gold, relevant_keys
from revise_stream.model import Observation, Query, Stream
from revise_stream.timeline import Key, candidates_at, observed_candidates


class KeyVersion:
    __slots__ = ("tau", "obs_ids", "interps")

    def __init__(self, tau: int, obs_ids: Tuple[str, ...], interps: List):
        self.tau, self.obs_ids, self.interps = tau, obs_ids, interps


class DerivedVersion:
    __slots__ = ("tau", "pins", "reason")

    def __init__(self, tau: int, pins: Dict[Key, int], reason: str):
        self.tau, self.pins, self.reason = tau, pins, reason


class BeliefStore:
    def __init__(self, stream: Stream, propagation: str = "on", commit: bool = False, policy: str = "P0c"):
        self.s = stream
        self.propagation = propagation
        self.commit = commit
        self.policy = policy
        self.keys: Dict[Key, List[KeyVersion]] = {}
        self.derived: Dict[Key, List[DerivedVersion]] = {}
        self.ingested: List[Observation] = []
        self.tau = 0
        self.cost = {"key_recomputes": 0, "derived_refreshes": 0, "writes": 0, "reads": 0}
        self._derived_keys = [(e, a, "") for a, spec in stream.attributes.items() if spec.derived for e in stream.entities]
        self._pending_until = -1

    # ---------------- write path ----------------
    def ingest_until(self, tau: int) -> None:
        for o in self.s.observations:
            if o.t_rep <= tau and o.t_rep > self._pending_until:
                self._ingest(o)
        self._pending_until = max(self._pending_until, tau)
        self.tau = max(self.tau, tau)

    def _admitted_key(self, key: Key, tau: int) -> List[Observation]:
        # the store's own view of admitted observations: those it ingested, minus
        # retractions and self-corrections it has seen (same rule as SEMANTICS §4)
        return [o for o in self.s.admitted_by_key(tau).get(key, [])]

    def _recompute_key(self, key: Key, tau: int, reason: str) -> None:
        obs = self._admitted_key(key, tau)
        interps = oracle_v1.key_interpretations(self.s, tau, key, self.policy) if obs else [(frozenset(), ())]
        if self.commit:
            interps = [min(interps, key=lambda it: (len(it[0]), -sum(1 for seg in it[1] if seg.end_hi != float("inf")), repr(it)))]
        self.keys.setdefault(key, []).append(KeyVersion(tau, tuple(o.id for o in obs), interps))
        self.cost["key_recomputes"] += 1

    def _version_index(self, key: Key, tau: int) -> int:
        vs = self.keys.get(key, [])
        idx = -1
        for i, v in enumerate(vs):
            if v.tau <= tau:
                idx = i
        return idx

    def _dependents(self, key: Key, tau: int) -> List[Key]:
        out = []
        for dk in self._derived_keys:
            if key in relevant_keys(self.s, tau, dk[0], dk[1], dk[2], oracle_v1.interpretations):
                out.append(dk)
        return out

    def _refresh_derived(self, dk: Key, tau: int, reason: str) -> None:
        pins = {k: self._version_index(k, tau) for k in relevant_keys(self.s, tau, dk[0], dk[1], dk[2], oracle_v1.interpretations)}
        self.derived.setdefault(dk, []).append(DerivedVersion(tau, pins, reason))
        self.cost["derived_refreshes"] += 1

    def _ingest(self, o: Observation) -> None:
        self.cost["writes"] += 1
        self.ingested.append(o)
        tau = o.t_rep
        if o.kind == "assert":
            if self.s.sources[o.source].cls == "blocked":
                return
            self._recompute_key(o.key, tau, "assert")
            for dk in self._dependents(o.key, tau):
                self._refresh_derived(dk, tau, "assert")          # ordinary belief updating
            # A-SELF: a same-origin correction withdraws its target. Normally target and correction
            # share a key and the recompute above already reflects the withdrawal; under extraction
            # errors the correction can land on another key (e.g. swapped entity/value), and the
            # withdrawal must still be applied to the target's key and propagated (found 3 Oct 2026
            # from 18 incremental-vs-replay disagreements in Setting 2, all of this kind).
            if o.op_cue == "correction" and o.op_of in self.s.self_corrections(tau):
                tgt = next((x for x in self.ingested if x.id == o.op_of), None)
                if tgt is not None and tgt.kind == "assert" and tgt.key != o.key:
                    self._recompute_key(tgt.key, tau, "retract")
                    if self.propagation == "on":
                        for dk in self._dependents(tgt.key, tau):
                            self._refresh_derived(dk, tau, "retract")
        elif o.kind == "retract":
            targets: List[Key] = []
            if o.target in self.s.sources:
                targets = sorted({x.key for x in self.ingested if x.kind == "assert" and x.source == o.target})
            else:
                tgt = next((x for x in self.ingested if x.id == o.target), None)
                if tgt is not None:
                    targets = [tgt.key]
            for k in targets:
                self._recompute_key(k, tau, "retract")
                if self.propagation == "on":
                    for dk in self._dependents(k, tau):
                        self._refresh_derived(dk, tau, "retract")  # justification propagation

    # ---------------- read path ----------------
    def _key_interps_at(self, key: Key, tau: int) -> List:
        idx = self._version_index(key, tau)
        return self.keys[key][idx].interps if idx >= 0 else [(frozenset(), ())]

    def _provider(self, tau: int, pins: Optional[Dict[Key, int]] = None):
        def prov(key: Key, t: int):
            if pins is not None and key in pins:
                vs = self.keys.get(key, [])
                interps = vs[pins[key]].interps if pins[key] >= 0 and vs else [(frozenset(), ())]
            else:
                interps = self._key_interps_at(key, tau)
            cands = set()
            for it in interps:
                cands |= observed_candidates(self.s, it[1], self.s.attributes[key[1]], t)
            return cands
        return prov

    def _interp_fn(self, stream: Stream, tau: int, policy: str = None, keys=None):
        keys = sorted(keys) if keys is not None else sorted(self.keys)
        from itertools import product
        per = [self._key_interps_at(k, tau) for k in keys]
        out = set()
        for combo in product(*per):
            err = frozenset().union(*[c[0] for c in combo]) if combo else frozenset()
            tls = tuple(sorted((k, c[1]) for k, c in zip(keys, combo) if c[1]))
            out.add((err, tls))
        return out

    def answer(self, q: Query) -> Dict[str, Any]:
        self.ingest_until(q.tau)
        self.cost["reads"] += 1
        s = self.s
        if q.slot == "reported":
            obs = [o for o in self.ingested if o.kind == "assert" and o.key == (q.entity, q.attr, q.ctx)]
            adm = {o.id for o in s.admitted(q.tau)}
            rep: Dict[str, List[str]] = {}
            for o in obs:
                if o.id in adm:
                    rep.setdefault(str(o.value), []).append(o.id)
            return self._fmt(q, {"status": "established", "assertion": {k: sorted(v) for k, v in sorted(rep.items())}, "alternatives": []},
                             sorted(x for v in rep.values() for x in v))
        if q.slot == "belief_asof":
            g = _value_gold(s, self._provider(q.tau_prime), (q.entity, q.attr, q.ctx), q.tau_prime)
            return self._fmt(q, g, self._prov_ids((q.entity, q.attr, q.ctx), q.tau_prime, g))
        key = (q.entity, q.attr, q.ctx) if q.slot != "yesno" else None
        if q.slot in ("current", "asof", "downstream"):
            t = q.t if q.t is not None else q.tau
            if s.attributes[q.attr].derived:
                vs = self.derived.get(key, [])
                ver = None
                for v in vs:
                    if v.tau <= q.tau:
                        ver = v
                pins = ver.pins if ver is not None else {}
                prov = self._provider(q.tau, pins)
                g = _value_gold(s, prov, key, t)
                prov_ids = self._path_prov(prov, key, t, g, q.tau)
            else:
                g = _value_gold(s, self._provider(q.tau), key, t)
                prov_ids = self._prov_ids(key, q.tau, g)
            return self._fmt(q, g, prov_ids)
        if q.slot == "yesno":
            p = q.prop
            if p["kind"] == "erroneous":
                adm = {o.id: o for o in s.admitted(q.tau)}
                if p["obs"] not in adm:
                    return self._fmt(q, _yesno_gold([]), [])
                k = adm[p["obs"]].key
                truths = [p["obs"] in it[0] for it in self._key_interps_at(k, q.tau)]
                return self._fmt(q, _yesno_gold(truths), [p["obs"]])
            k = (p["entity"], p["attr"], p.get("ctx", ""))
            if p["kind"] == "changed":
                truths = [_changed(it[1], p["from"], p["to"]) for it in self._key_interps_at(k, q.tau)]
                return self._fmt(q, _yesno_gold(truths), list(self._prov_ids(k, q.tau, None)))
            t = p.get("t", q.tau)
            truths = [p["value"] in c for c in candidates_at(s, self._provider(q.tau), k, t)]
            return self._fmt(q, _yesno_gold(truths), list(self._prov_ids(k, q.tau, None)))
        raise ValueError(q.slot)

    def _path_prov(self, prov, key: Key, t: int, g, tau: int) -> List[str]:
        """Provenance for a derived answer: observations asserting a (key, value) binding
        used on a derivation path that yields the answer (the store's own justification)."""
        trace: list = []
        cands = candidates_at(self.s, prov, key, t, trace=trace)
        wanted = {v for S in cands for v in S}
        pairs = set()
        for (k, v, used) in trace:
            if k == key and v in wanted:
                pairs |= used
        adm = self.s.admitted_by_key(tau)
        return sorted({o.id for (k, v) in pairs for o in adm.get(k, []) if o.value == v})

    def _prov_ids(self, key: Key, tau: int, g) -> List[str]:
        idx = self._version_index(key, tau)
        if idx < 0:
            return []
        ids = self.keys[key][idx].obs_ids
        if g is None or g.get("status") in ("unresolved", "possible", "unknown"):
            return sorted(ids)
        vals = set()
        a = g.get("assertion")
        vals |= set(a) if isinstance(a, list) else ({a} if a is not None else set())
        return sorted(o.id for o in self.s.admitted_by_key(tau).get(key, []) if o.value in vals) or sorted(ids)

    @staticmethod
    def _fmt(q: Query, g: Dict[str, Any], prov: List[str]) -> Dict[str, Any]:
        return {"query_id": q.id, "status": g["status"], "assertion": g["assertion"],
                "alternatives": g.get("alternatives", []), "provenance": sorted(set(prov))}
