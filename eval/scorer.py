"""Deterministic scorer for the shared output contract (plan §3.4).

score(answer, gold, stream, query) -> dict with:
  exact      1/0  primary credit: status matches, and assertion / alternative set matches after normalisation
  lenient    1/0  secondary: status matches and alternatives ⊇ gold (unresolved), or exact
  committed  1/0  the answer selected one interpretation on an unresolved/possible slot (premature commitment)
  malformed  1/0  schema-invalid after the repair allowance (caller sets this; scorer treats as wrong)
  prov_precision, prov_recall  (None when no provenance is applicable)
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    jsonschema = None

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract", "answer.schema.json")
with open(SCHEMA_PATH) as _f:
    SCHEMA = json.load(_f)

STATUSES = ("established", "possible", "unresolved", "unknown")


def validate(answer: Dict[str, Any]) -> Optional[str]:
    """Return None if the answer is schema-valid, else an error message."""
    if jsonschema is None:
        if not isinstance(answer, dict) or answer.get("status") not in STATUSES:
            return "invalid"
        return None
    try:
        jsonschema.validate(answer, SCHEMA)
        return None
    except jsonschema.ValidationError as e:  # type: ignore
        return e.message


def norm(v: Any) -> Any:
    """Canonical form: lower-cased stripped strings, sorted lists (as tuples), bools, numbers, None."""
    if v is None or isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, (list, tuple, set, frozenset)):
        return tuple(sorted((norm(x) for x in v), key=lambda x: (x is None, str(x))))
    if isinstance(v, dict):
        return tuple(sorted((norm(k), norm(val)) for k, val in v.items()))
    return v


def _alt_set(alts: List[Any]) -> Set[Any]:
    return {norm(a) for a in alts}


def supporting_ids(stream, query, gold) -> Set[str]:
    """Observation ids that lie on an oracle justification path for the query's answer
    (revise_stream.gold.support_ids). For yes/no slots: the key's admitted observations
    (erroneous: the observation itself and its competitors)."""
    from revise_stream import oracle_v1
    from revise_stream.gold import support_ids
    tau = query.tau_prime if query.slot == "belief_asof" else query.tau
    adm = stream.admitted(tau)
    if query.slot == "yesno":
        p = query.prop
        if p["kind"] == "erroneous":
            o = next((x for x in adm if x.id == p["obs"]), None)
            return {x.id for x in adm if o is not None and x.key == o.key}
        key = (p["entity"], p["attr"], p.get("ctx", ""))
        t = p.get("t", tau)
        if p["kind"] == "holds":
            return support_ids(stream, tau, key, t, oracle_v1.interpretations)
        return {x.id for x in adm if x.key == key}
    key = (query.entity, query.attr, query.ctx)
    if query.slot == "reported":
        return {x.id for x in adm if x.key == key}
    t = tau if query.slot in ("current", "downstream", "belief_asof") else query.t
    if query.slot == "belief_asof":
        t = query.tau_prime
    elif query.t is not None and query.slot in ("current", "downstream"):
        t = query.t
    return support_ids(stream, tau, key, t, oracle_v1.interpretations)


def score(answer: Dict[str, Any], gold: Dict[str, Any], stream=None, query=None) -> Dict[str, Any]:
    out = {"exact": 0, "lenient": 0, "committed": 0, "malformed": 0, "prov_precision": None, "prov_recall": None}
    if validate(answer) is not None:
        out["malformed"] = 1
        return out
    st, gs = answer["status"], gold["status"]
    ga, gal = norm(gold["assertion"]), _alt_set(gold.get("alternatives", []))
    aa, aal = norm(answer.get("assertion")), _alt_set(answer.get("alternatives", []))
    if gs in ("unresolved", "possible") and st == "established":
        out["committed"] = 1
    if gs == "unresolved" and st == "possible" and aa is not None:
        out["committed"] = 1   # qualified, but still picked one interpretation on a value slot
    if st == gs:
        if gs == "established":
            out["exact"] = int(aa == ga)
        elif gs == "possible":
            out["exact"] = int(aa == ga)
        elif gs == "unresolved":
            out["exact"] = int(aal == gal and aa is None)
            out["lenient"] = int(gal <= aal and aa is None)
        else:  # unknown
            out["exact"] = 1
    out["lenient"] = max(out["lenient"], out["exact"])
    if stream is not None and query is not None and query.slot != "reported":
        sup = supporting_ids(stream, query, gold)
        cited = set(answer.get("provenance", []))
        if cited:
            out["prov_precision"] = len(cited & sup) / len(cited)
        if sup:
            out["prov_recall"] = len(cited & sup) / len(sup)
    return out
