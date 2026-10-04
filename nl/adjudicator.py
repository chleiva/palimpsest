"""Query-time LLM adjudication over an append-only claims log (the falsifier baseline
in Settings 2–3), under the shared output contract.

The log given to the model is the shared extracted-claims log filtered to the query's
belief time (write-time ingestion is what the filter simulates). The model receives the
shared instruction (contract/shared_prompt.md), the vocabulary, the log, and the query
rendered as its answer slot, and must return the contract JSON. One repair attempt.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import json
from nl.llm import extract_json
from nl.templater import OUTLETS, day_to_date, surface_map
from revise_stream.model import Observation, Query, Stream

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = open(os.path.join(ROOT, "contract", "shared_prompt.md")).read()
REPAIR = open(os.path.join(ROOT, "contract", "repair_prompt.md")).read()


def claim_line(stream: Stream, o: Observation) -> str:
    cls = stream.sources[o.source].cls
    if o.kind == "retract":
        what = f"source {o.target}" if o.target in stream.sources else f"report {o.target}"
        return f"[{o.id}] day {o.t_rep}, {o.source} ({cls}): WITHDRAWN {what}"
    v = o.value
    cue = ""
    if o.valid_cue == "since":
        cue = f" since day {o.valid_t}"
    elif o.valid_cue == "at":
        cue = f" as of day {o.valid_t}"
    op = ""
    if o.op_cue == "change":
        op = f"; stated change" + (f" from {o.op_from}" if o.op_from is not None else "")
    elif o.op_cue == "correction":
        op = f"; stated correction of report {o.op_of}"
    return f"[{o.id}] day {o.t_rep}, {o.source} ({cls}): {o.attr}({o.entity}) = {v}{cue}{op}"


def rules_block(stream: Stream) -> str:
    out = []
    for r in stream.rules:
        body = " and ".join(f"{a}({x}) = {y}" for (a, x, y) in r.body)
        exc = "; exception: " + ", ".join(f"{a}({x}) = {y}" for (a, x, y) in r.exceptions) if r.exceptions else ""
        out.append(f"- {r.head[0]}({r.head[1]}) = {r.head[2]} if {body} ({r.kind}{exc})")
    attrs = []
    for a, s in stream.attributes.items():
        attrs.append(f"{a}: {s.type}, {s.cardinality}-valued, {'changeable' if s.changeable else 'stable'}"
                     + (", derived" if s.derived else "") + ("" if s.competing_values else ", differing values coexist"))
    return "Attributes:\n" + "\n".join(attrs) + ("\nRules:\n" + "\n".join(out) if out else "")


def render_query(q: Query) -> str:
    if q.slot == "current":
        return f"Query {q.id}: what is {q.attr}({q.entity}) now (day {q.t if q.t is not None else q.tau})? Answer slot: value of {q.attr} for {q.entity}."
    if q.slot == "downstream":
        return f"Query {q.id}: what is the derived attribute {q.attr}({q.entity}) now (day {q.t if q.t is not None else q.tau})? Answer slot: value of {q.attr} for {q.entity}."
    if q.slot == "asof":
        return f"Query {q.id}: what was {q.attr}({q.entity}) on day {q.t}, given everything known now? Answer slot: value of {q.attr} for {q.entity} at day {q.t}."
    if q.slot == "belief_asof":
        return f"Query {q.id}: using only reports available up to day {q.tau_prime}, what was the justified value of {q.attr}({q.entity}) then? Answer slot: value of {q.attr} for {q.entity}."
    if q.slot == "reported":
        return f"Query {q.id}: which values of {q.attr}({q.entity}) have been reported (and still stand, i.e. not withdrawn)? Answer slot: object mapping each reported value to the list of report ids."
    p = q.prop
    if p["kind"] == "erroneous":
        return f"Query {q.id}: is report {p['obs']} erroneous? Answer slot: yes/no proposition (assertion true/false)."
    if p["kind"] == "changed":
        return f"Query {q.id}: did {p['attr']}({p['entity']}) change from {p['from']} to {p['to']}? Answer slot: yes/no proposition."
    return f"Query {q.id}: does {p['attr']}({p['entity']}) = {p['value']} hold on day {p.get('t', q.tau)}? Answer slot: yes/no proposition."


def adjudication_request(stream: Stream, log: List[Observation], q: Query, topk: Optional[int] = None,
                         nl_lines: Optional[Dict[str, str]] = None) -> dict:
    """With nl_lines, the log shown is the raw natural-language reports (no extraction at
    all: the pure query-time alternative); otherwise the shared extracted-claims log."""
    tau = q.tau
    entries = [o for o in log if o.t_rep <= tau]
    if topk is not None:
        # matched-cost variant: the most recent topk entries plus every entry on the queried key
        key = (q.entity, q.attr) if q.slot != "yesno" else (q.prop.get("entity"), q.prop.get("attr"))
        onkey = [o for o in entries if o.kind == "assert" and (o.entity, o.attr) == key]
        rest = [o for o in entries if o not in onkey][-topk:]
        entries = sorted(set(onkey + rest), key=lambda o: (o.t_rep, int(o.id[1:])))
    if nl_lines is not None:
        from nl.extractor import vocabulary_block
        lines = "\n".join(nl_lines[o.id] for o in entries)
        user = (f"{vocabulary_block(stream)}\n{rules_block(stream)}\n\nReports (append-only, in order of publication; a report saying that a report "
                f"or a source has been withdrawn withdraws it for everything after it):\n{lines}\n\n{render_query(q)}\n"
                f"Observation ids for provenance are the bracketed ids. Values must use entity ids (e.g. city2), ISO dates, true/false, lower-case strings. Output the JSON object only; keep any explanation under 200 characters or omit it.")
        return {"id": f"adjnl:{stream.stream_id}:{q.id}", "system": SHARED, "messages": [{"role": "user", "content": user}],
                "max_tokens": 600, "temperature": 0.0}
    lines = "\n".join(claim_line(stream, o) for o in entries)
    user = (f"{rules_block(stream)}\n\nEvidence log (append-only; later lines were reported later; a WITHDRAWN line "
            f"withdraws the named report or source for everything after it):\n{lines}\n\n{render_query(q)}\n"
            f"Observation ids for provenance are the bracketed ids. Values must use the ids/formats shown in the log. Output the JSON object only; keep any explanation under 200 characters or omit it.")
    return {"id": f"adj:{stream.stream_id}:{q.id}", "system": SHARED, "messages": [{"role": "user", "content": user}],
            "max_tokens": 600, "temperature": 0.0}


def repair_request(orig: dict, raw: str, error: str) -> dict:
    return {"id": orig["id"].replace("adjnl:", "repnl:").replace("adj:", "rep:"), "system": orig["system"],
            "messages": orig["messages"] + [{"role": "assistant", "content": raw[:3000]},
                                            {"role": "user", "content": REPAIR.replace("{{error}}", error).replace("{{raw}}", raw[:1500])}],
            "max_tokens": 400, "temperature": 0.0}


def _salvage(text: str) -> Optional[dict]:
    """A JSON object truncated inside its (unscored) explanation field: drop the field."""
    i = text.find('"explanation"')
    if i == -1:
        return None
    head = text[:i].rstrip().rstrip(",")
    start = head.find("{")
    if start == -1:
        return None
    try:
        return json.loads(head[start:] + "}")
    except Exception:
        return None


def parse_answer(q: Query, text: str) -> Optional[dict]:
    d = extract_json(text) or _salvage(text)
    if not isinstance(d, dict):
        return None
    d.setdefault("query_id", q.id)
    d["query_id"] = q.id
    d.setdefault("alternatives", [])
    d.setdefault("provenance", [])
    d.setdefault("assertion", None)
    if isinstance(d.get("provenance"), list):
        d["provenance"] = sorted({str(x) for x in d["provenance"]})
    if "explanation" in d and not isinstance(d["explanation"], str):
        d.pop("explanation")
    if isinstance(d.get("explanation"), str):
        d["explanation"] = d["explanation"][:600]
    return d
