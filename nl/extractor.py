"""Claim extraction (Setting 2, step 3): one report line -> one structured observation.

Shared by every system. The extractor sees the vocabulary (entity ids with surface
names, attributes with types, source keys with outlet names) and ONE report line; it
returns a JSON object. The mock extractor inverts the templater from the hidden
structured observation and injects controlled noise (slot errors, missed and spurious
operator cues, missed temporal cues), for pipeline tests and for the extractor-noise
analysis.
"""
from __future__ import annotations

import json
import random
from typing import Any, Dict, List, Optional, Tuple

from nl.llm import extract_json
from nl.templater import OUTLETS, base_of, date_to_day, day_to_date, surface_map
from revise_stream.model import Observation, Stream

EXTRACT_SYSTEM = """You convert one news-style report about people and organisations into a structured claim.
Output exactly one JSON object and nothing else:
{"kind": "assert" | "retract",
 "entity": <entity id>, "attr": <attribute>, "value": <value>,
 "valid": {"cue": "none" | "since" | "at", "date": "YYYY-MM-DD" or null},
 "op_cue": "none" | "change" | "correction", "op_from": <previous value or null>, "op_of": <report id or null>,
 "target": <report id or source key or null>}

Rules:
- Use entity ids from the vocabulary (e.g. "p2", "org1", "city3"), never surface names. Dates as YYYY-MM-DD.
- "kind": "retract" only when the report says a report or a source's reports have been withdrawn; then set "target" to the withdrawn report id (e.g. "o12") or the source key (e.g. "forum"), and leave entity/attr/value null.
- "valid.cue": "since" if the report says the fact holds since a date; "at" if it says the fact held as of a date; otherwise "none" (do not infer a date from the report's dateline).
- "op_cue": "change" only if the report explicitly states a change (moved, relocated, joined, appointed, switched, stopped, replacing, leaving); then "op_from" is the previous value if stated, else null. "correction" only if the report explicitly says an earlier report was wrong or is being corrected; then "op_of" is that report's id. Otherwise "none". Do not add a cue the text does not state; do not drop one it states.
- Attribute values: employer/ceo/residence/hq_city/citizenship/position are entity ids; remote is true/false; birth_date is YYYY-MM-DD (YYYY-MM or YYYY when the report gives only a month or a year); nickname is a lower-case string.
- One claim per report. If the report is about two attributes, choose the main one."""


def vocabulary_block(stream: Stream) -> str:
    sm = surface_map(stream)
    ents = ", ".join(f"{k} = {v}" for k, v in sm.items() if k != v)
    attrs = []
    for a, spec in stream.attributes.items():
        if spec.derived:
            continue
        attrs.append(f"{a} ({spec.type}, {'multi' if spec.cardinality == 'multi' else 'single'}-valued)")
    srcs = ", ".join(f"{k} = {OUTLETS[k]}" for k in stream.sources)
    return f"Entities: {ents}\nAttributes: {', '.join(attrs)}\nSource keys: {srcs}"


def extraction_request(stream: Stream, oid: str, line: str) -> dict:
    return {"id": f"ext:{stream.stream_id}:{oid}", "system": EXTRACT_SYSTEM,
            "messages": [{"role": "user", "content": f"{vocabulary_block(stream)}\n\nReport:\n{line}\n\nJSON:"}],
            "max_tokens": 220, "temperature": 0.0}


def parse_extraction(stream: Stream, o_meta: Observation, text: str) -> Tuple[Optional[Observation], Optional[str]]:
    """Build an Observation from the model's JSON, keeping id/source/report time from the
    metadata (which is not extracted). Returns (observation, error)."""
    d = extract_json(text)
    if not d:
        return None, "no json"
    try:
        if d.get("kind") == "retract":
            tgt = d.get("target")
            if tgt is None:
                return None, "retract without target"
            return Observation(id=o_meta.id, t_rep=o_meta.t_rep, source=o_meta.source, kind="retract", target=str(tgt)), None
        attr = d.get("attr")
        if attr not in stream.attributes or stream.attributes[attr].derived:
            return None, f"bad attr {attr}"
        ent = d.get("entity")
        if ent not in stream.entities:
            return None, f"bad entity {ent}"
        v = d.get("value")
        spec = stream.attributes[attr]
        if spec.type == "bool":
            v = bool(v) if isinstance(v, bool) else str(v).lower() in ("true", "yes", "1")
        elif spec.type == "entity":
            if v not in stream.entities:
                return None, f"bad value {v}"
        elif spec.type == "string":
            v = str(v).strip().lower()
        else:
            v = str(v)
        valid = d.get("valid") or {}
        cue = valid.get("cue", "none") if isinstance(valid, dict) else "none"
        vt = None
        if cue in ("since", "at"):
            vt = date_to_day(str(valid.get("date") or ""), base_of(stream)) if valid.get("date") else None
            if vt is None:
                cue = "none"
        op = d.get("op_cue") or "none"
        if op not in ("none", "change", "correction"):
            op = "none"
        op_from = d.get("op_from") if op == "change" else None
        if op_from is not None and spec.type == "entity" and op_from not in stream.entities:
            op_from = None
        if op_from is not None and spec.type == "bool" and not isinstance(op_from, bool):
            op_from = str(op_from).lower() in ("true", "yes", "1")
        op_of = str(d.get("op_of")) if (op == "correction" and d.get("op_of")) else None
        if op == "correction" and op_of is None:
            op = "none"
        return Observation(id=o_meta.id, t_rep=o_meta.t_rep, source=o_meta.source, kind="assert", entity=ent, attr=attr,
                           value=v, valid_cue=cue, valid_t=vt, op_cue=op, op_from=op_from, op_of=op_of), None
    except Exception as e:  # defensive: any malformed field counts as an extraction failure
        return None, f"parse error {e}"


def mock_extractor_handler(stream: Stream, noise: Dict[str, float], seed: int = 0):
    """Returns a handler(request)->text that inverts the templater from the hidden
    observation and injects noise: slot_error (wrong value), missed_cue (drop op cue),
    spurious_cue (add change cue), missed_valid (drop temporal cue)."""
    by_id = {o.id: o for o in stream.observations}
    sm = surface_map(stream)
    rng = random.Random(seed)

    def handler(req: dict) -> str:
        oid = req["id"].split(":")[-1]
        o = by_id[oid]
        if o.kind == "retract":
            return json.dumps({"kind": "retract", "target": o.target})
        v, op, op_from, cue, vt = o.value, o.op_cue, o.op_from, o.valid_cue, o.valid_t
        spec = stream.attributes[o.attr]
        if rng.random() < noise.get("slot_error", 0):
            if spec.type == "entity":
                pool = [e for e in stream.entities if e != v and e[:1] == str(v)[:1]]
                v = rng.choice(pool) if pool else v
            elif spec.type == "bool":
                v = not v
        if op != "none" and rng.random() < noise.get("missed_cue", 0):
            op, op_from = "none", None
        elif op == "none" and spec.changeable and rng.random() < noise.get("spurious_cue", 0):
            op = "change"
        if cue != "none" and rng.random() < noise.get("missed_valid", 0):
            cue, vt = "none", None
        d = {"kind": "assert", "entity": o.entity, "attr": o.attr, "value": v,
             "valid": {"cue": cue, "date": (day_to_iso(vt, base_of(stream)) if vt is not None else None)},
             "op_cue": op, "op_from": op_from, "op_of": o.op_of if op == "correction" else None, "target": None}
        return json.dumps(d)

    return handler


def day_to_iso(t: int, base=None) -> str:
    import datetime as _dt
    from nl.templater import BASE
    return ((base or BASE) + _dt.timedelta(days=int(t) - 1)).isoformat()


def extraction_diagnostics(stream: Stream, frozen: List[Observation], extracted: Dict[str, Optional[Observation]]) -> Dict[str, Any]:
    """Slot errors and ambiguity errors of the extracted stream against the frozen
    (text-level) labels. missed_ambiguity: text has no operator cue, extractor added one.
    spurious_ambiguity: text has a cue, extractor dropped it."""
    n = slot = missed_amb = spur_amb = valid_err = fail = 0
    kind_err = 0
    for o in frozen:
        x = extracted.get(o.id)
        n += 1
        if x is None:
            fail += 1
            continue
        if x.kind != o.kind:
            kind_err += 1
            continue
        if o.kind == "retract":
            if x.target != o.target:
                slot += 1
            continue
        if (x.entity, x.attr, x.value) != (o.entity, o.attr, o.value):
            slot += 1
        if o.op_cue == "none" and x.op_cue != "none":
            missed_amb += 1
        if o.op_cue != "none" and x.op_cue == "none":
            spur_amb += 1
        if (x.valid_cue, x.valid_t) != (o.valid_cue, o.valid_t):
            valid_err += 1
    return {"n": n, "failed": fail, "kind_error": kind_err, "slot_error_rate": slot / max(1, n), "missed_ambiguity_rate": missed_amb / max(1, n),
            "spurious_ambiguity_rate": spur_amb / max(1, n), "valid_cue_error_rate": valid_err / max(1, n), "failure_rate": fail / max(1, n)}
