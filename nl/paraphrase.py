"""Paraphrase (Setting 2, step 2) and the cue-recovery check that precedes the
evaluation-set freeze (plan §3.4).

A paraphrase must keep: the names, the value, any date, any explicit statement of a
change or of a correction (and the corrected report's id), and must not introduce one.
The deterministic check looks for date strings and cue markers; the model-based check
re-extracts the cues with the cheap model, blind to the structured source.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from nl.templater import day_to_date
from revise_stream.model import Observation

PARAPHRASE_SYSTEM = """Rewrite the report in one natural sentence (two at most) with different wording, keeping its meaning exactly.
Keep: the names, the value, any date, and the leading "[id] (outlet, date):" prefix unchanged.
Operator words matter. If the original states that something CHANGED (moved, relocated, joined, appointed, switched, stopped,
replacing, leaving, has moved its headquarters), the rewrite must still state a change with such a verb. If the original does NOT
state a change (e.g. "X works for Y", "Y lists X among its staff since <date>", "X lives in Z"), the rewrite must not introduce one:
do not write joined, moved, became, started, switched, began, took up, now, no longer, new. A "since <date>" is a date, not a change.
If the original says an earlier report (by id) was wrong or is corrected, keep that statement and the id; otherwise do not add one.
If the original says a report or a source was withdrawn, say so with "withdrawn" or "retracted".
Examples:
  "Osmara Group lists Ravi Chandran among its staff since 1 January 2026." -> "Ravi Chandran has been on Osmara Group's staff since 1 January 2026."  (no change verb)
  "Alex Moreno has switched to working remotely since 10 January 2026." -> "Alex Moreno switched to remote work, and has worked remotely since 10 January 2026."  (change kept)
Output only the rewritten report."""

CHANGE_MARKERS = re.compile(r"\b(moved|moving|relocat\w*|joined|joining|appointed|switch\w*|stopped|no longer|back on site|replac\w*|leaving|left|transferr\w*|now (?:lives|works|based)|new (?:home|employer|job|address|headquarters|chief))\b", re.I)
CORR_MARKERS = re.compile(r"\b(correct\w*|wrong\w*|incorrect\w*|inaccurate\w*|in error|erroneous\w*|mistaken\w*|mistake|retract\w*|amend\w*|contrary to|not right|was false|rectif\w*)\b", re.I)
DATE_RE = re.compile(r"\b\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b")


def paraphrase_request(stream_id: str, oid: str, line: str) -> dict:
    return {"id": f"para:{stream_id}:{oid}", "system": PARAPHRASE_SYSTEM,
            "messages": [{"role": "user", "content": line}], "max_tokens": 160, "temperature": 0.7}


def deterministic_cue_check(o: Observation, text: str) -> Tuple[bool, str]:
    """True if the paraphrase is consistent with the intended cues at the string level."""
    body = text.split("):", 1)[1] if "):" in text else text
    has_date = bool(DATE_RE.search(body))
    if o.kind == "retract":
        return (bool(re.search(r"withdr\w*|retract\w*|pulled|rescind\w*|revok\w*|disown\w*", body, re.I)), "retraction marker")
    if o.valid_cue in ("since", "at") and not has_date:
        return False, "date lost"
    if o.valid_cue == "none" and has_date and o.attr != "birth_date":
        return False, "date added"
    has_chg, has_corr = bool(CHANGE_MARKERS.search(body)), bool(CORR_MARKERS.search(body))
    if o.op_cue == "change" and not has_chg:
        return False, "change cue lost"
    if o.op_cue == "correction" and not (has_corr and (o.op_of or "") in body):
        return False, "correction cue or target id lost"
    if o.op_cue == "none" and (has_chg or has_corr):
        return False, "cue added"
    return True, "ok"


def cue_recovery_request(stream_id: str, oid: str, line: str) -> dict:
    """Cheap-model pass, blind to the structured source: which cues does the text state?"""
    sys = ("Read one report and answer with JSON only: {\"states_change\": true|false, \"states_correction\": true|false, "
           "\"corrected_report_id\": <id or null>, \"has_date\": true|false}. "
           "states_change is true ONLY if the text explicitly says the situation is different from before: a move, a relocation, joining or "
           "leaving an organisation, an appointment replacing someone, switching to/stopping something, 'no longer', 'now ... instead'. "
           "A plain statement of a current fact with a start date ('X has worked for Y since 3 March 2026', 'X is not a remote worker since ...') "
           "does NOT state a change: answer false. states_correction is true only if the text explicitly says an earlier report was wrong, incorrect "
           "or is corrected. has_date is true only if a calendar date appears in the body of the report after the colon (ignore the dateline in parentheses).")
    return {"id": f"cue:{stream_id}:{oid}", "system": sys, "messages": [{"role": "user", "content": line}], "max_tokens": 60, "temperature": 0.0}


def model_cue_check(o: Observation, reply: Optional[dict]) -> Tuple[bool, str]:
    if not reply:
        return False, "no reply"
    if o.kind == "retract":
        return True, "n/a"
    if bool(reply.get("states_change")) != (o.op_cue == "change"):
        return False, "change cue mismatch"
    if bool(reply.get("states_correction")) != (o.op_cue == "correction"):
        return False, "correction cue mismatch"
    if o.attr != "birth_date" and bool(reply.get("has_date")) != (o.valid_cue in ("since", "at")):
        return False, "date mismatch"
    return True, "ok"


def strip_cues(o: Observation, reasons: str) -> Observation:
    """Adjudication outcome when the text is judged to have lost a cue: the frozen label
    reflects the text as presented (the oracle then re-runs without that cue)."""
    kw = dict(o.__dict__)
    if "change" in reasons or "correction" in reasons or "cue" in reasons:
        kw.update(op_cue="none", op_from=None, op_of=None)
    if "date" in reasons:
        kw.update(valid_cue="none", valid_t=None)
    return Observation(**kw)
