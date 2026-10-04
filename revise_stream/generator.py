"""REVISE-Stream generator (Phase 1, structured setting).

Three layers per stream (plan §3.1): the world trajectory (hidden from all systems),
the observation stream with provenance (what systems see), and the oracle's justified
beliefs (gold, computed by revise_stream.gold from the observations only).

Perturbation menu (each controlled by a rate in GenConfig): delayed reports, unknown
change dates (no temporal cue), reversals, correlated copies (same origin), false
statements from trusted sources, genuine low-trust corrections, self-corrections
(A-SELF), cross-origin corrections, explicit retraction of observations and of a
whole source. The generator never calls the oracle to construct observations.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .model import Stream, load_stream, stream_from_dict

ATTRS = {
    # person attributes
    "employer":   {"type": "entity", "cardinality": "single", "changeable": True,  "error_allowed": True},
    "residence":  {"type": "entity", "cardinality": "multi",  "changeable": True,  "error_allowed": True},
    "remote":     {"type": "bool",   "cardinality": "single", "changeable": True,  "error_allowed": True},
    "birth_date": {"type": "date",   "cardinality": "single", "changeable": False, "error_allowed": True},
    "nickname":   {"type": "string", "cardinality": "multi",  "changeable": False, "error_allowed": True, "competing_values": False},
    # org attributes
    "hq_city":    {"type": "entity", "cardinality": "single", "changeable": True,  "error_allowed": True},
    "ceo":        {"type": "entity", "cardinality": "single", "changeable": True,  "error_allowed": True},
    # derived
    "work_city":      {"type": "entity", "cardinality": "single", "changeable": True, "error_allowed": False, "derived": True},
    "local_tax_city": {"type": "entity", "cardinality": "multi",  "changeable": True, "error_allowed": False, "derived": True},
    "ceo_city":       {"type": "entity", "cardinality": "single", "changeable": True, "error_allowed": False, "derived": True},
}
RULES = [
    {"id": "r_work", "kind": "defeasible", "head": ["work_city", "?e", "?c"],
     "body": [["employer", "?e", "?x"], ["hq_city", "?x", "?c"]], "exceptions": [["remote", "?e", True]]},
    {"id": "r_tax", "kind": "strict", "head": ["local_tax_city", "?e", "?c"], "body": [["residence", "?e", "?c"]]},
    {"id": "r_ceo_city", "kind": "defeasible", "head": ["ceo_city", "?o", "?c"],
     "body": [["ceo", "?o", "?p"], ["work_city", "?p", "?c"]]},
]
PERSON_ATTRS = ["employer", "residence", "remote", "birth_date", "nickname"]
ORG_ATTRS = ["hq_city", "ceo"]
VOLATILE = ["employer", "residence", "remote", "hq_city", "ceo"]
DERIVED_OF = {"employer": ["work_city"], "hq_city": ["work_city"], "remote": ["work_city"],
              "residence": ["local_tax_city"], "ceo": ["ceo_city"]}


@dataclass
class GenConfig:
    seed: int = 0
    T: int = 60                     # valid-time horizon (days)
    n_persons: int = 5
    n_orgs: int = 3
    n_cities: int = 6
    max_obs_per_key: int = 7        # bounds per-key enumeration (2^7 subsets)
    p_change_per_10d: float = 0.18  # per volatile attribute
    p_reversal: float = 0.25        # a change reverts within 10 days
    reports_mean: float = 1.8       # reporting sources per world fact
    p_copy: float = 0.25            # correlated copy from a same-origin source
    delay_p: float = 0.45           # geometric delay parameter (mean ~1.2 days)
    p_long_delay: float = 0.12      # heavy-tail delay (10–25 days)
    p_cue_since: float = 0.5        # explicit valid-time cue
    p_change_cue: float = 0.35      # 'change' op cue on reports of changes
    p_change_from: float = 0.5      # ... with 'from' presupposition
    p_error: Dict[str, float] = field(default_factory=lambda: {"trusted": 0.06, "standard": 0.12, "low": 0.30})
    p_self_correct: float = 0.45    # erroneous report later self-corrected (A-SELF)
    p_cross_correct: float = 0.35   # ... else corrected by another origin with a correction cue
    p_low_corrector: float = 0.5    # cross-origin corrector is a low-trust source (genuine low-trust correction)
    p_retract_obs: float = 0.12     # explicit retraction of an observation (erroneous or not)
    p_retract_source: float = 0.35  # one source is retracted wholesale at some belief time
    n_queries: int = 40
    n_random_taus: int = 3
    attack_rate: float = 0.0        # poisoned assertions as a fraction of honest ones
    attack_channel: str = "low"     # "low": a fresh anonymous low-trust source; "trusted": a compromised trusted source
    attack_cue: float = 0.5         # share of poisoned reports that carry a false 'change' cue


SOURCES = {
    "press":    {"class": "trusted",  "origin": "g_press"},
    "wire":     {"class": "standard", "origin": "g_press"},     # copies press
    "registry": {"class": "trusted",  "origin": "g_registry"},
    "hr":       {"class": "trusted",  "origin": "g_hr"},
    "wiki":     {"class": "standard", "origin": "g_wiki"},
    "mirror":   {"class": "standard", "origin": "g_wiki"},      # copies wiki
    "blog":     {"class": "low",      "origin": "g_blog"},
    "forum":    {"class": "low",      "origin": "g_forum"},
}
COPIERS = {"press": "wire", "wiki": "mirror"}


class Gen:
    def __init__(self, cfg: GenConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.persons = [f"p{i}" for i in range(cfg.n_persons)]
        self.orgs = [f"org{i}" for i in range(cfg.n_orgs)]
        self.cities = [f"city{i}" for i in range(cfg.n_cities)]
        self.entities = self.persons + self.orgs + self.cities
        self.obs: List[Dict[str, Any]] = []
        self.world: List[Dict[str, Any]] = []     # facts: entity, attr, value, t0, prev
        self._n = 0

    # ---------------- world ----------------
    def _rand_value(self, attr: str, exclude=None):
        r = self.rng
        if attr in ("employer",):
            pool = [o for o in self.orgs if o != exclude]
        elif attr in ("residence", "hq_city"):
            pool = [c for c in self.cities if c != exclude]
        elif attr == "ceo":
            pool = [p for p in self.persons if p != exclude]
        elif attr == "remote":
            return not exclude if exclude is not None else r.random() < 0.3
        elif attr == "birth_date":
            return f"{r.randint(1960, 2000)}-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}"
        elif attr == "nickname":
            return r.choice(["ace", "bee", "cap", "dot", "eli", "fox", "gus", "ivy"])
        else:
            raise ValueError(attr)
        return r.choice(pool)

    def build_world(self):
        r, cfg = self.rng, self.cfg
        for e in self.persons:
            for a in PERSON_ATTRS:
                if a == "nickname" and r.random() < 0.5:
                    continue
                self.world.append({"entity": e, "attr": a, "value": self._rand_value(a), "t0": 1, "prev": None, "kind": "initial"})
        for o in self.orgs:
            for a in ORG_ATTRS:
                self.world.append({"entity": o, "attr": a, "value": self._rand_value(a), "t0": 1, "prev": None, "kind": "initial"})
        # changes
        current = {(f["entity"], f["attr"]): f["value"] for f in self.world}
        for (e, a), v in list(current.items()):
            if a not in VOLATILE:
                continue
            t = 1
            while True:
                t += r.randint(3, 12)
                if t > cfg.T - 3:
                    break
                if r.random() < cfg.p_change_per_10d:
                    nv = self._rand_value(a, exclude=current[(e, a)])
                    self.world.append({"entity": e, "attr": a, "value": nv, "t0": t, "prev": current[(e, a)], "kind": "change"})
                    if r.random() < cfg.p_reversal:
                        tb = t + r.randint(2, 10)
                        if tb < cfg.T - 2:
                            self.world.append({"entity": e, "attr": a, "value": current[(e, a)], "t0": tb, "prev": nv, "kind": "reversal"})
                            current[(e, a)] = current[(e, a)]
                            t = tb
                            continue
                    current[(e, a)] = nv

    # ---------------- observations ----------------
    def _oid(self) -> str:
        self._n += 1
        return f"o{self._n}"

    def _delay(self) -> int:
        r, cfg = self.rng, self.cfg
        if r.random() < cfg.p_long_delay:
            return r.randint(10, 25)
        d = 0
        while r.random() > cfg.delay_p and d < 8:
            d += 1
        return d

    def _count(self, e, a) -> int:
        return sum(1 for o in self.obs if o["kind"] == "assert" and o["entity"] == e and o["attr"] == a)

    def _add_assert(self, e, a, v, t_rep, source, valid=None, op_cue="none", op_from=None, op_of=None, truth=None):
        if self._count(e, a) >= self.cfg.max_obs_per_key:
            return None
        o = {"id": self._oid(), "t": int(t_rep), "source": source, "kind": "assert", "entity": e, "attr": a, "value": v}
        if valid:
            o["valid"] = valid
        if op_cue != "none":
            o["op_cue"] = op_cue
        if op_from is not None:
            o["op_from"] = op_from
        if op_of is not None:
            o["op_of"] = op_of
        o["_truth"] = truth            # generator-side label, stripped before saving
        self.obs.append(o)
        return o

    def report_world(self):
        r, cfg = self.rng, self.cfg
        src_names = list(SOURCES)
        for f in self.world:
            e, a, v, t0 = f["entity"], f["attr"], f["value"], f["t0"]
            n_rep = max(1, min(3, int(r.expovariate(1 / cfg.reports_mean)) + 1))
            reporters = r.sample([s for s in src_names if s not in COPIERS.values()], k=min(n_rep, 6))
            for s in reporters:
                cls = SOURCES[s]["class"]
                t_rep = t0 + self._delay()
                if t_rep > cfg.T:
                    continue
                valid = {"cue": "since", "t": t0} if (ATTRS[a]["changeable"] and r.random() < cfg.p_cue_since) else None
                op_cue, op_from = "none", None
                if f["kind"] in ("change", "reversal") and r.random() < cfg.p_change_cue:
                    op_cue = "change"
                    if r.random() < cfg.p_change_from:
                        op_from = f["prev"]
                err = r.random() < cfg.p_error[cls]
                val = self._rand_value(a, exclude=v) if err else v
                if err:
                    op_cue, op_from = "none", None      # an erroneous report carries no change cue
                o = self._add_assert(e, a, val, t_rep, s, valid, op_cue, op_from, truth=(not err))
                if o is None:
                    continue
                # correlated copy from the same origin
                if s in COPIERS and r.random() < cfg.p_copy:
                    self._add_assert(e, a, val, t_rep + 1 + self._delay(), COPIERS[s], valid, op_cue, op_from, truth=(not err))
                # follow-ups to an erroneous report
                if err:
                    u = r.random()
                    if u < cfg.p_self_correct:
                        self._add_assert(e, a, v, t_rep + 1 + self._delay(), s, valid, "correction", None, op_of=o["id"], truth=True)
                    elif u < cfg.p_self_correct + cfg.p_cross_correct:
                        pool = [x for x in src_names if SOURCES[x]["origin"] != SOURCES[s]["origin"]]
                        low = [x for x in pool if SOURCES[x]["class"] == "low"]
                        corr = r.choice(low) if (low and r.random() < cfg.p_low_corrector) else r.choice(pool)
                        self._add_assert(e, a, v, t_rep + 1 + self._delay(), corr, valid, "correction", None, op_of=o["id"], truth=True)
        # explicit retractions of observations (erroneous ones preferentially, some correct ones)
        for o in list(self.obs):
            if o["kind"] != "assert":
                continue
            p = cfg.p_retract_obs * (3.0 if o["_truth"] is False else 0.6)
            if r.random() < p:
                t_r = o["t"] + 1 + self._delay()
                if t_r <= cfg.T:
                    self.obs.append({"id": self._oid(), "t": int(t_r), "source": o["source"], "kind": "retract", "target": o["id"], "_truth": None})
        # wholesale source retraction
        if r.random() < cfg.p_retract_source:
            s = r.choice([x for x in src_names if SOURCES[x]["class"] != "trusted"])
            t_r = r.randint(cfg.T // 2, cfg.T)
            self.obs.append({"id": self._oid(), "t": int(t_r), "source": "registry", "kind": "retract", "target": s, "_truth": None})
        # attacker (plan: explicit attacker model, secondary RQ)
        if cfg.attack_rate > 0:
            honest = [o for o in self.obs if o["kind"] == "assert"]
            k = max(1, int(round(cfg.attack_rate * len(honest))))
            src = "anon" if cfg.attack_channel == "low" else "press"
            if src == "anon":
                SOURCES.setdefault("anon", {"class": "low", "origin": "g_anon"})
            keys = sorted({(o["entity"], o["attr"]) for o in honest})
            for _ in range(k):
                e, a = r.choice(keys)
                truth_now = [f for f in self.world if f["entity"] == e and f["attr"] == a]
                cur = sorted(truth_now, key=lambda f: f["t0"])[-1]["value"]
                val = self._rand_value(a, exclude=cur)
                t_rep = r.randint(2, cfg.T)
                cue = "change" if (ATTRS[a]["changeable"] and r.random() < cfg.attack_cue) else "none"
                o = self._add_assert(e, a, val, t_rep, src, None, cue, None, truth=False)
                if o is not None:
                    o["_poison"] = True
        self.obs.sort(key=lambda o: (o["t"], int(o["id"][1:])))

    # ---------------- queries ----------------
    def _downstream_keys(self, stream: Stream, tau: int, e: str, a: str) -> List[Tuple[str, str]]:
        """Derived keys whose justification can depend on (e, a) at belief time tau
        (inverse of gold.relevant_keys, computed with the oracle's dependency relation)."""
        from .gold import relevant_keys
        from . import oracle_v1
        out = []
        for d, spec in stream.attributes.items():
            if not spec.derived:
                continue
            for ent in stream.entities:
                try:
                    if (e, a, "") in relevant_keys(stream, tau, ent, d, "", oracle_v1.interpretations):
                        out.append((ent, d))
                except Exception:
                    pass
        return out

    def make_queries(self) -> List[Dict[str, Any]]:
        stream = stream_from_dict({"stream_id": "tmp", "domain": {"entities": self.entities, "attributes": ATTRS, "rules": RULES},
                                   "sources": SOURCES, "observations": [{k: v for k, v in o.items() if not k.startswith("_")} for o in self.obs],
                                   "queries": []})
        return self.make_queries_generic(stream)

    def make_queries_generic(self, stream: Stream) -> List[Dict[str, Any]]:
        """Event-driven and grid queries for any stream whose observations are in self.obs."""
        r, cfg = self.rng, self.cfg
        qs: List[Dict[str, Any]] = []
        by_id = {o["id"]: o for o in self.obs}
        qn = [0]
        T = cfg.T if max(o["t"] for o in self.obs) <= cfg.T else max(o["t"] for o in self.obs)
        if stream is None:    # generated streams: rebuild from the generator's own domain
            stream = stream_from_dict({"stream_id": "tmp", "domain": {"entities": self.entities, "attributes": ATTRS, "rules": RULES},
                                       "sources": dict(SOURCES), "observations": [{k: v for k, v in o.items() if not k.startswith("_")} for o in self.obs],
                                       "queries": []})
        # assembled streams (Setting 3) pass their own stream, whose domain/sources are used as given

        def add(slot, tau, tags=(), **kw):
            qn[0] += 1
            q = {"id": f"q{qn[0]}", "slot": slot, "tau": int(tau), "tags": list(tags)}
            q.update(kw)
            qs.append(q)
            return q

        # event-driven queries: at every retraction / correction / change-cue report
        events = [o for o in self.obs if o["kind"] == "retract" or o.get("op_cue") in ("correction", "change")]
        for ev in events:
            tau = ev["t"]
            if ev["kind"] == "retract":
                if ev["target"] in by_id:
                    tgt = by_id[ev["target"]]
                    keys = [(tgt["entity"], tgt["attr"])]
                else:
                    keys = sorted({(o["entity"], o["attr"]) for o in self.obs if o["kind"] == "assert" and o["source"] == ev["target"]})[:2]
            else:
                keys = [(ev["entity"], ev["attr"])]
            for (e, a) in keys:
                add("current", tau, ("retraction_consequence", "event"), entity=e, attr=a)
                add("current", tau - 1, ("pre",), entity=e, attr=a)
                for (ent, d) in self._downstream_keys(stream, tau, e, a)[:4]:
                    add("downstream", tau, ("retraction_consequence", "event"), entity=ent, attr=d)
                    add("downstream", tau - 1, ("pre",), entity=ent, attr=d)
                if ev["kind"] != "retract" and ev.get("op_cue") == "correction" and ev.get("op_of") in by_id:
                    add("yesno", tau, ("event",), prop={"kind": "erroneous", "obs": ev["op_of"]})
                if ev["kind"] != "retract" and ev.get("op_cue") == "change" and ev.get("op_from") is not None:
                    add("yesno", tau, ("event",), prop={"kind": "changed", "entity": e, "attr": a, "from": ev["op_from"], "to": ev["value"]})
        # random-time queries over the bitemporal grid
        taus = sorted(r.sample(range(5, T + 1), k=min(cfg.n_random_taus, T - 5)))
        obs_keys = sorted({(o["entity"], o["attr"]) for o in self.obs if o["kind"] == "assert"})
        for tau in taus:
            for (e, a) in r.sample(obs_keys, k=min(6, len(obs_keys))):
                kind = r.choice(["asof", "belief_asof", "reported", "holds", "current", "downstream"])
                if kind == "asof":
                    add("asof", tau, ("grid",), entity=e, attr=a, t=r.randint(1, tau))
                elif kind == "belief_asof":
                    add("belief_asof", tau, ("grid",), entity=e, attr=a, tau_prime=r.randint(2, tau))
                elif kind == "reported":
                    add("reported", tau, ("grid",), entity=e, attr=a)
                elif kind == "holds":
                    vals = [o["value"] for o in self.obs if o["kind"] == "assert" and (o["entity"], o["attr"]) == (e, a)]
                    add("yesno", tau, ("grid",), prop={"kind": "holds", "entity": e, "attr": a, "value": r.choice(vals), "t": r.randint(1, tau)})
                elif kind == "current":
                    add("current", tau, ("grid",), entity=e, attr=a)
                else:
                    for (ent, d) in self._downstream_keys(stream, tau, e, a)[:1]:
                        add("downstream", tau, ("grid",), entity=ent, attr=d)
        return qs

    # ---------------- assemble ----------------
    def stream_dict(self, stream_id: str) -> Dict[str, Any]:
        self.build_world()
        self.report_world()
        qs = self.make_queries()
        obs_out = []
        for o in self.obs:
            d = {k: v for k, v in o.items() if not k.startswith("_")}
            obs_out.append(d)
        return {
            "stream_id": stream_id,
            "meta": {"generator": "revise_stream.generator v0.1", "config": asdict(self.cfg),
                     "n_obs": len(obs_out), "n_world_facts": len(self.world)},
            "domain": {"entities": self.entities, "attributes": ATTRS, "rules": RULES},
            "sources": dict(SOURCES),
            "observations": obs_out,
            "queries": qs,
            # hidden layers, kept in a separate file by generate_file()
            "_world": self.world,
            "_truth": {o["id"]: o["_truth"] for o in self.obs if o["kind"] == "assert"},
            "_poison": [o["id"] for o in self.obs if o.get("_poison")],
        }


def generate(seed: int, cfg: Optional[GenConfig] = None, stream_id: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cfg = cfg or GenConfig()
    cfg.seed = seed
    g = Gen(cfg)
    d = g.stream_dict(stream_id or f"s1_{seed:04d}")
    hidden = {"world": d.pop("_world"), "truth": d.pop("_truth"), "poison": d.pop("_poison")}
    return d, hidden


def select_queries(stream: Stream, gold: Dict[str, Dict[str, Any]], n: int, rng: random.Random,
                   quota=(0.30, 0.30, 0.40)) -> List[str]:
    """Declared stratified selection (pre-registration): of n primary queries, 30% are
    warranted-retraction consequence queries (downstream slots first, then direct), 30% non-warranted event queries (they
    feed the unsupported-propagation endpoint), 40% bitemporal-grid queries balanced
    between resolvable and unresolved. Every event query keeps its 'pre' companion
    (asked at tau-1), which does not count toward n. Shortfalls in one stratum are
    filled from the others. Returns kept query ids."""
    qs = stream.queries
    byid = {q.id: q for q in qs}
    pres = {(q.entity, q.attr, q.slot, q.tau): q.id for q in qs if "pre" in q.tags}
    warr = [q for q in qs if "event" in q.tags and gold[q.id]["warranted"]]
    nonw = [q for q in qs if "event" in q.tags and not gold[q.id]["warranted"]]
    grid = [q for q in qs if "grid" in q.tags]
    res = [q for q in grid if gold[q.id]["status"] == "established"]
    unres = [q for q in grid if gold[q.id]["status"] != "established"]
    for lst in (warr, nonw, res, unres):
        rng.shuffle(lst)
    # downstream warranted queries (the primary endpoint) are taken first; pop() takes from the end
    warr.sort(key=lambda q: q.slot == "downstream")
    want = [round(n * quota[0]), round(n * quota[1]), n - round(n * quota[0]) - round(n * quota[1])]
    keep: List[str] = []

    def take_event(pool, k):
        taken = 0
        while pool and taken < k:
            q = pool.pop()
            keep.append(q.id)
            pid = pres.get((q.entity, q.attr, q.slot, q.tau - 1))
            if pid:
                keep.append(pid)
            taken += 1
        return taken

    got = [take_event(warr, want[0]), take_event(nonw, want[1]), 0]
    g = 0
    while g < want[2] and (res or unres):
        pool = res if (len(res) >= len(unres) and res) else unres
        keep.append(pool.pop().id); g += 1
    got[2] = g
    short = n - sum(got)
    for pool, is_event in ((warr, True), (nonw, True), (res, False), (unres, False)):
        while short > 0 and pool:
            if is_event:
                take_event(pool, 1)
            else:
                keep.append(pool.pop().id)
            short -= 1
    return keep


def write_stream(path: str, d: Dict[str, Any], hidden: Dict[str, Any], gold: Dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(d, f, indent=1)
    with open(path.replace(".json", ".hidden.json"), "w") as f:
        json.dump(hidden, f, indent=1)
    with open(path.replace(".json", ".gold.json"), "w") as f:
        json.dump(gold, f, indent=1)
