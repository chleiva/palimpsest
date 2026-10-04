"""Structured observation -> natural-language report (Setting 2, step 1; deterministic).

Entity ids are rendered with fictional surface names (no world knowledge to lean on);
days are rendered as calendar dates; sources as outlet names. Every report is shown
to all systems as "[id] (outlet, date): sentence". Operator cues are rendered
explicitly when present (a stated move / a stated correction) and absent otherwise,
so the cue-recovery check has something concrete to recover.
"""
from __future__ import annotations

import datetime as _dt
import random
from typing import Dict, Optional

from revise_stream.model import Observation, Stream

PERSONS = ["Alex Moreno", "Dana Whitfield", "Ravi Chandran", "Mei Okafor", "Jonas Lindqvist", "Priya Natarajan", "Tomas Erlich", "Lena Ashby"]
ORGS = ["Veltran Systems", "Osmara Group", "Kestrel Logistics", "Halvard Energy", "Brightwater Labs", "Corvid Analytics"]
CITIES = ["Tessaly", "Bramwick", "Corvane", "Elmstead", "Norreth", "Sable Harbor", "Quillmere", "Ashford Vale"]
COUNTRIES = ["Valdoria", "Marenne", "Ostrava Union", "Keldar", "Sorenia", "Tavish Republic"]
TITLES = ["chief archivist", "deputy director", "senior fellow", "head of research", "board chair", "visiting professor"]


class _Outlets(dict):
    """Outlet names for source keys. Settings 1-2 use the fixed names below; other keys (the
    Setting 3 assembler's 'none_wd_unreferenced', 'stated_in_q123', 'url_example_org',
    'wd_editors') get deterministic pseudonymous names so that no real source is shown."""

    def __missing__(self, key: str) -> str:
        if key == "wd_editors":
            name = "the OpenPedia editors"
        elif key.startswith("none_"):
            name = "an unreferenced OpenPedia entry"
        elif key.startswith("stated_in_"):
            name = f"Catalogue {len([k for k in self if k.startswith('stated_in_')]) + 1}"
        elif key.startswith("url_"):
            name = f"Website {len([k for k in self if k.startswith('url_')]) + 1}"
        else:
            name = key
        self[key] = name
        return name


OUTLETS = _Outlets({"press": "The Daily Ledger", "wire": "Ledger Wire", "registry": "the Civic Registry", "hr": "the HR bulletin",
                    "wiki": "OpenPedia", "mirror": "the OpenPedia mirror", "blog": "a personal blog", "forum": "a forum post"})
BASE = _dt.date(2026, 1, 1)


def base_of(stream: Optional[Stream]) -> _dt.date:
    """Calendar date of day 1. Generated streams use BASE; assembled streams carry the real
    date of their first revision in meta['base_date'] so that rendered dates are the real ones."""
    bd = (stream.meta or {}).get("base_date") if stream is not None else None
    return _dt.date.fromisoformat(bd) if bd else BASE


def day_to_date(t: int, base: Optional[_dt.date] = None) -> str:
    return ((base or BASE) + _dt.timedelta(days=int(t) - 1)).strftime("%-d %B %Y")


def date_to_day(s: str, base: Optional[_dt.date] = None) -> Optional[int]:
    for fmt in ("%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return (_dt.datetime.strptime(s.strip(), fmt).date() - (base or BASE)).days + 1
        except ValueError:
            continue
    return None


def _roles(stream: Stream) -> Dict[str, str]:
    """Infer person/org/city/country/title for opaque entity ids (Setting 3 Q-ids) from the
    attributes they appear in. Ids with the generated prefixes p/org/city keep their prefix."""
    role = {}
    for o in stream.observations:
        if o.kind != "assert":
            continue
        if o.attr in ("employer", "residence", "citizenship", "birth_date", "position", "remote", "nickname"):
            role.setdefault(o.entity, "p")
        elif o.attr in ("hq_city", "ceo"):
            role.setdefault(o.entity, "org")
        if isinstance(o.value, str):
            if o.attr == "employer":
                role.setdefault(o.value, "org")
            elif o.attr in ("hq_city", "residence"):
                role.setdefault(o.value, "city")
            elif o.attr == "citizenship":
                role.setdefault(o.value, "country")
            elif o.attr == "position":
                role.setdefault(o.value, "title")
            elif o.attr == "ceo":
                role.setdefault(o.value, "p")
    return role


def surface_map(stream: Stream) -> Dict[str, str]:
    m = {}
    pools = {"p": PERSONS, "org": ORGS, "city": CITIES, "country": COUNTRIES, "title": TITLES}
    counters = {k: 0 for k in pools}
    roles = _roles(stream)

    def take(kind: str) -> str:
        i = counters[kind]; counters[kind] += 1
        pool = pools[kind]
        name = pool[i % len(pool)]
        return name if i < len(pool) else f"{name} {i // len(pool) + 1}"      # 'Alex Moreno 2' when a pool is exhausted

    for e in stream.entities:
        if e.startswith("p") and not e.startswith("Q"):
            m[e] = take("p")
        elif e.startswith("org"):
            m[e] = take("org")
        elif e.startswith("city"):
            m[e] = take("city")
        elif e in roles:
            m[e] = take(roles[e])
        else:
            m[e] = e
    return m


def value_text(attr: str, v, sm: Dict[str, str]) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, str) and v in sm:
        return sm[v]
    if attr == "birth_date":
        parts = str(v).split("-")
        if len(parts) == 1 or parts[1] == "00":          # year precision (Wikidata)
            return parts[0]
        if len(parts) == 2 or parts[2] == "00":          # month precision
            return _dt.date(int(parts[0]), int(parts[1]), 1).strftime("%B %Y")
        return _dt.date(int(parts[0]), int(parts[1]), int(parts[2])).strftime("%-d %B %Y")
    return str(v)


def render(stream: Stream, o: Observation, sm: Dict[str, str], rng: random.Random) -> str:
    """One report sentence (without the [id] (outlet, date) prefix)."""
    base_date = base_of(stream)
    day_to_date = lambda t: globals()["day_to_date"](t, base_date)  # noqa: E731
    if o.kind == "retract":
        if o.target in stream.sources:
            return f"{OUTLETS[o.target].capitalize()}'s reports have all been withdrawn; nothing from that source should be relied on."
        return f"The report {o.target} has been withdrawn by its publisher."
    e = sm[o.entity]
    v = value_text(o.attr, o.value, sm)
    since = f" since {day_to_date(o.valid_t)}" if o.valid_cue == "since" else ""
    at = f" as of {day_to_date(o.valid_t)}" if o.valid_cue == "at" else ""
    pick = lambda *xs: xs[rng.randrange(len(xs))]
    a = o.attr
    if a == "residence":
        base = pick(f"{e} lives in {v}{since}{at}.", f"{e} is resident in {v}{since}{at}.", f"{e}'s home is in {v}{since}{at}.")
        if o.op_cue == "change":
            frm = f" from {sm[o.op_from]}" if o.op_from else ""
            base = pick(f"{e} has moved{frm} to {v}{since}.", f"{e} relocated{frm} to {v}{since}.")
    elif a == "employer":
        base = pick(f"{e} works for {v}{since}{at}.", f"{e} is employed by {v}{since}{at}.", f"{v} lists {e} among its staff{since}{at}.")
        if o.op_cue == "change":
            frm = f", leaving {sm[o.op_from]}," if o.op_from else ""
            base = pick(f"{e} has joined {v}{frm}{since}.".replace(",,", ","), f"{e} moved to {v}{frm}{since}.".replace(",,", ","))
    elif a == "remote":
        base = (pick(f"{e} works remotely{since}{at}.", f"{e} is a remote worker{since}{at}.") if o.value
                else pick(f"{e} works on site, not remotely{since}{at}.", f"{e} is not a remote worker{since}{at}."))
        if o.op_cue == "change":
            base = (f"{e} has switched to working remotely{since}." if o.value else f"{e} has stopped working remotely and is back on site{since}.")
    elif a == "birth_date":
        base = pick(f"{e} was born on {v}.", f"{e}'s date of birth is {v}.")
    elif a == "nickname":
        base = pick(f"{e} goes by the nickname \"{v}\".", f"Friends call {e} \"{v}\".")
    elif a == "citizenship":
        base = pick(f"{e} is a citizen of {v}{since}{at}.", f"{e} holds {v} citizenship{since}{at}.")
    elif a == "position":
        base = pick(f"{e} holds the position of {v}{since}{at}.", f"{e} serves as {v}{since}{at}.")
        if o.op_cue == "change":
            frm = f", previously {sm.get(o.op_from, o.op_from)}," if o.op_from else ""
            base = f"{e} has been appointed {v}{frm}{since}.".replace(",,", ",")
    elif a == "hq_city":
        base = pick(f"{e} is headquartered in {v}{since}{at}.", f"{e}'s head office is in {v}{since}{at}.")
        if o.op_cue == "change":
            frm = f" from {sm[o.op_from]}" if o.op_from else ""
            base = pick(f"{e} has moved its headquarters{frm} to {v}{since}.", f"{e} relocated its head office{frm} to {v}{since}.")
    elif a == "ceo":
        base = pick(f"{v} is the chief executive of {e}{since}{at}.", f"{e}'s CEO is {v}{since}{at}.")
        if o.op_cue == "change":
            frm = f", replacing {sm[o.op_from]}," if o.op_from else ""
            base = f"{v} has been appointed chief executive of {e}{frm}{since}.".replace(",,", ",")
    else:
        base = f"{e}'s {a} is {v}{since}{at}."
    if o.op_cue == "correction":
        base = pick(f"Correction: the earlier report {o.op_of} was wrong. {base}",
                    f"{base} This corrects the earlier report {o.op_of}, which was in error.")
    return base


def render_stream(stream: Stream, seed: int = 0) -> Dict[str, str]:
    """{observation id: full line '[id] (outlet, date): sentence'}"""
    sm = surface_map(stream)
    rng = random.Random(seed)
    out = {}
    bd = base_of(stream)
    for o in stream.observations:
        line = f"[{o.id}] ({OUTLETS[o.source]}, {day_to_date(o.t_rep, bd)}): {render(stream, o, sm, rng)}"
        out[o.id] = line
    return out
