"""REVISE-Stream data model (Phase 0).

Implements the declared semantics in docs/SEMANTICS.md v0.1. Supported valid-time
cues in Phase 0: none, since, at. (until / interval and negative polarity are
deferred to Phase 1 and raise NotImplementedError.)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

INF = float("inf")
CLASS_RANK = {"low": 0, "standard": 1, "trusted": 2, "blocked": -1}


@dataclass(frozen=True)
class AttributeSpec:
    name: str
    type: str                    # entity | date | int | string | bool
    cardinality: str             # single | multi
    changeable: bool
    error_allowed: bool = True
    derived: bool = False
    competing_values: bool = True   # do differing values on the same key dispute each other?


@dataclass(frozen=True)
class Rule:
    id: str
    head: Tuple[str, str, str]                  # (attr, ?e, ?v)
    body: Tuple[Tuple[str, str, str], ...]      # ((attr, ?x, ?y), ...)
    kind: str = "defeasible"                    # strict | defeasible
    exceptions: Tuple[Tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Source:
    id: str
    cls: str                     # trusted | standard | low | blocked
    origin: str


@dataclass(frozen=True)
class Observation:
    id: str
    t_rep: int
    source: str
    kind: str                    # assert | retract
    entity: Optional[str] = None
    attr: Optional[str] = None
    value: Any = None
    ctx: str = ""
    polarity: bool = True
    valid_cue: str = "none"      # none | since | at
    valid_t: Optional[int] = None
    op_cue: str = "none"         # none | change | correction
    op_from: Any = None          # for change: previous value
    op_of: Optional[str] = None  # for correction: corrected observation id
    target: Optional[str] = None # for retract: observation id or source id

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.entity, self.attr, self.ctx)

    @property
    def anchor(self) -> int:
        if self.valid_cue in ("since", "at"):
            return int(self.valid_t)
        if self.valid_cue == "none":
            return self.t_rep
        raise NotImplementedError(f"valid cue {self.valid_cue} deferred to Phase 1")


@dataclass(frozen=True)
class Query:
    id: str
    slot: str                    # current | asof | belief_asof | yesno | reported | downstream
    tau: int                     # belief time at which the query is asked
    entity: Optional[str] = None
    attr: Optional[str] = None
    ctx: str = ""
    t: Optional[int] = None      # valid time for asof; t_now for current/downstream (default tau)
    tau_prime: Optional[int] = None  # for belief_asof
    prop: Optional[Dict[str, Any]] = None  # for yesno: {"kind": holds|changed|erroneous, ...}
    tags: Tuple[str, ...] = ()


@dataclass
class Stream:
    stream_id: str
    entities: List[str]
    attributes: Dict[str, AttributeSpec]
    rules: List[Rule]
    sources: Dict[str, Source]
    observations: List[Observation]
    queries: List[Query]
    meta: Dict[str, Any] = field(default_factory=dict)
    _cache: Dict[Any, Any] = field(default_factory=dict, repr=False, compare=False)

    def invalidate(self) -> None:
        self._cache.clear()

    def self_corrections(self, tau: int) -> Dict[str, str]:
        """A-SELF (SEMANTICS §4): a correction whose source shares the origin of the
        corrected observation's source withdraws that observation. Returns
        {withdrawn observation id: correcting observation id}."""
        obs = {o.id: o for o in self.observations if o.t_rep <= tau}
        out = {}
        for o in obs.values():
            if o.kind == "assert" and o.op_cue == "correction" and o.op_of in obs:
                tgt = obs[o.op_of]
                if self.sources[o.source].origin == self.sources[tgt.source].origin:
                    out[tgt.id] = o.id
        return out

    def admitted(self, tau: int) -> List[Observation]:
        """Admitted, non-retracted assertions with t_rep <= tau (SEMANTICS §3–4)."""
        ck = ("adm", tau)
        if ck in self._cache:
            return self._cache[ck]
        obs = [o for o in self.observations if o.t_rep <= tau]
        retracted_obs = {o.target for o in obs if o.kind == "retract" and o.target in {x.id for x in obs}}
        retracted_obs |= set(self.self_corrections(tau))
        retracted_src = {o.target for o in obs if o.kind == "retract" and o.target in self.sources}
        out = []
        for o in obs:
            if o.kind != "assert":
                continue
            if self.sources[o.source].cls == "blocked":
                continue
            if o.id in retracted_obs or o.source in retracted_src:
                continue
            if not o.polarity:
                raise NotImplementedError("negative polarity deferred to Phase 1")
            out.append(o)
        self._cache[ck] = out
        return out

    def admitted_by_key(self, tau: int) -> Dict[Tuple[str, str, str], List[Observation]]:
        ck = ("adm_by_key", tau)
        if ck not in self._cache:
            d: Dict[Tuple[str, str, str], List[Observation]] = {}
            for o in self.admitted(tau):
                d.setdefault(o.key, []).append(o)
            self._cache[ck] = d
        return self._cache[ck]

    def rank(self, o: Observation) -> int:
        return CLASS_RANK[self.sources[o.source].cls]

    def corroborated(self, o: Observation, tau: int) -> bool:
        """Same key and value asserted by an admitted observation from a different origin."""
        og = self.sources[o.source].origin
        return any(p.key == o.key and p.value == o.value and p.id != o.id
                   and self.sources[p.source].origin != og for p in self.admitted(tau))


def _lit(x: List[str]) -> Tuple[str, str, str]:
    return (x[0], x[1], x[2])


def load_stream(path: str) -> Stream:
    with open(path) as f:
        d = json.load(f)
    return stream_from_dict(d)


def stream_from_dict(d: Dict[str, Any]) -> Stream:
    attrs = {k: AttributeSpec(name=k, **v) for k, v in d["domain"]["attributes"].items()}
    rules = [Rule(id=r["id"], head=_lit(r["head"]), body=tuple(_lit(b) for b in r["body"]),
                  kind=r.get("kind", "defeasible"), exceptions=tuple(_lit(x) for x in r.get("exceptions", [])))
             for r in d["domain"].get("rules", [])]
    sources = {k: Source(id=k, cls=v["class"], origin=v["origin"]) for k, v in d["sources"].items()}
    obs = []
    for o in d["observations"]:
        vc = o.get("valid", {"cue": "none"})
        obs.append(Observation(
            id=o["id"], t_rep=o["t"], source=o["source"], kind=o["kind"],
            entity=o.get("entity"), attr=o.get("attr"), value=o.get("value"), ctx=o.get("ctx", ""),
            polarity=o.get("polarity", True), valid_cue=vc.get("cue", "none"), valid_t=vc.get("t"),
            op_cue=o.get("op_cue", "none"), op_from=o.get("op_from"), op_of=o.get("op_of"),
            target=o.get("target")))
    qs = [Query(id=q["id"], slot=q["slot"], tau=q["tau"], entity=q.get("entity"), attr=q.get("attr"),
                ctx=q.get("ctx", ""), t=q.get("t"), tau_prime=q.get("tau_prime"), prop=q.get("prop"),
                tags=tuple(q.get("tags", []))) for q in d["queries"]]
    return Stream(stream_id=d["stream_id"], entities=d["domain"]["entities"], attributes=attrs, rules=rules,
                  sources=sources, observations=obs, queries=qs, meta=d.get("meta", {}))
