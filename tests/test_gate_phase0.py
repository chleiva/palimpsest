"""Phase 0 gate (plan §7): the two independent oracle implementations must produce
identical interpretation sets (ERR sets + induced timelines) and identical gold on
three hand-written streams, and the Alex stream must reproduce the four expected
behaviours of plan §1.1."""
import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from revise_stream import oracle_v1, oracle_v2  # noqa: E402
from revise_stream.gold import all_gold, gold_for  # noqa: E402
from revise_stream.model import load_stream  # noqa: E402

STREAMS = sorted(glob.glob(os.path.join(ROOT, "revise_stream", "streams", "*.json")))


def _expectations(path):
    with open(path) as f:
        return {q["id"]: q for q in json.load(f)["queries"]}


@pytest.mark.parametrize("path", STREAMS, ids=[os.path.basename(p) for p in STREAMS])
def test_oracles_agree_on_interpretations(path):
    s = load_stream(path)
    taus = sorted({q.tau for q in s.queries} | {q.tau_prime for q in s.queries if q.tau_prime is not None}
                  | {o.t_rep for o in s.observations})
    for tau in taus:
        a = oracle_v1.interpretations(s, tau)
        b = oracle_v2.interpretations(s, tau)
        assert a == b, f"{s.stream_id} tau={tau}: v1={sorted(map(repr,a))}\nv2={sorted(map(repr,b))}"
        assert len(a) >= 1, f"{s.stream_id} tau={tau}: no admissible interpretation"


@pytest.mark.parametrize("path", STREAMS, ids=[os.path.basename(p) for p in STREAMS])
def test_oracles_agree_on_gold_and_match_expectations(path):
    s = load_stream(path)
    g1 = all_gold(s, oracle_v1.interpretations)
    g2 = all_gold(s, oracle_v2.interpretations)
    assert g1 == g2
    exp = _expectations(path)
    for q in s.queries:
        e = exp[q.id]
        assert g1[q.id]["status"] == e["expect"], f"{s.stream_id}/{q.id}: {g1[q.id]} expected {e['expect']}"
        if "expect_value" in e:
            assert g1[q.id]["assertion"] == e["expect_value"], f"{s.stream_id}/{q.id}: {g1[q.id]}"


def test_alex_four_behaviours():
    s = load_stream(os.path.join(ROOT, "revise_stream", "streams", "alex.json"))
    g = all_gold(s, oracle_v2.interpretations)
    # "Did Alex move?" -> possible, not established
    assert g["q_move"]["status"] == "possible"
    # "Was the London report wrong?" -> evidence does not establish it
    assert g["q_london_wrong"]["status"] == "possible"
    # "What locations have been reported?" -> both, with provenance
    assert g["q_reported"]["assertion"] == {"london": ["o1"], "paris": ["o2"]}
    # a conclusion depending on Alex having left London is unresolved, not warranted
    assert g["q_tax_now"]["status"] == "unresolved" and g["q_tax_now"]["warranted"] is False
    assert sorted(map(str, g["q_tax_now"]["alternatives"])) == sorted(map(str, [["london"], ["paris"], ["london", "paris"]]))
    # current residence: three alternatives, none selected
    assert g["q_current"]["status"] == "unresolved"
    assert len(g["q_current"]["alternatives"]) == 3
    # exactly four interpretations at tau=2 (SEMANTICS §10 table)
    assert len(oracle_v2.interpretations(s, 2)) == 4


def test_acme_retraction_is_warranted():
    from functools import partial
    s = load_stream(os.path.join(ROOT, "revise_stream", "streams", "acme.json"))
    g = all_gold(s, oracle_v1.interpretations)
    assert g["q_work_t5"]["warranted"] is False      # uncued low-source competing report: unresolved
    assert g["q_work_t7"]["warranted"] is True       # retraction of o3 removes the competitor
    assert g["q_work_t7"]["assertion"] == "lisbon"   # ... and propagates through the cued HQ move
    assert g["q_work_t9"]["status"] == "unknown"     # defeasible exception blocks the rule
    # P0c: the cued HQ move is established and warranted at tau=4; under literal P0 it is unresolved
    assert g["q_hq_t4"]["status"] == "established" and g["q_hq_t4"]["warranted"] is True
    g0 = all_gold(s, partial(oracle_v1.interpretations, policy="P0"))
    assert g0["q_hq_t4"]["status"] == "unresolved"
    # the cued report is still disputable by a LATER competitor: add one and check
    import copy
    from revise_stream.model import Observation
    s2 = copy.deepcopy(s)
    s2.observations.append(Observation(id="o10", t_rep=5, source="blog", kind="assert", entity="globex", attr="hq_city", value="madrid"))
    s2.invalidate()
    from revise_stream.model import Query
    q = Query(id="x", slot="current", tau=5, entity="globex", attr="hq_city")
    from revise_stream.gold import gold_for
    assert gold_for(s2, q, oracle_v1.interpretations)["status"] == "unresolved"


def test_always_abstain_and_always_commit_discriminate():
    """Gate part (b): on the hand-written streams the two references must split:
    always-abstain is right only on unresolved/unknown slots, always-commit (take the
    latest report) only on resolvable ones."""
    sys.path.insert(0, ROOT)
    from eval.scorer import score
    from baselines.references import always_abstain, always_commit
    tot = {"abstain": [0, 0], "commit": [0, 0]}   # [resolvable correct, unresolved correct]
    n = [0, 0]
    for path in STREAMS:
        s = load_stream(path)
        g = all_gold(s, oracle_v2.interpretations)
        for q in s.queries:
            if q.slot == "reported":
                continue
            idx = 0 if g[q.id]["status"] == "established" else 1
            n[idx] += 1
            tot["abstain"][idx] += score(always_abstain(s, q), g[q.id], s, q)["exact"]
            tot["commit"][idx] += score(always_commit(s, q), g[q.id], s, q)["exact"]
    assert n[0] > 0 and n[1] > 0
    assert tot["abstain"][0] == 0 and tot["abstain"][1] > 0
    assert tot["commit"][0] > 0 and tot["commit"][1] < n[1]


def test_self_correction_withdraws_and_resolves():
    """A-SELF: a same-origin correction withdraws the earlier report; the corrected value
    is established (and the change is warranted); a later cross-origin low-trust report
    reopens the dispute under P0."""
    s = load_stream(os.path.join(ROOT, "revise_stream", "streams", "birthdate.json"))
    assert s.self_corrections(10) == {"o9": "o10"}
    assert "o9" not in {o.id for o in s.admitted(10)}
    g = all_gold(s, oracle_v2.interpretations)
    assert g["q_cit_t9"]["assertion"] == "india"
    assert g["q_cit_t10"]["status"] == "established" and g["q_cit_t10"]["assertion"] == "nepal"
    assert g["q_cit_t10"]["warranted"] is True
    assert g["q_cit_reported_t10"]["assertion"] == {"nepal": ["o10"]}   # withdrawn report is not 'reported'
    assert g["q_cit_t11"]["status"] == "unresolved"
    # the registry's correction of the wiki report (different origins) is NOT a withdrawal
    assert "o1" in {o.id for o in s.admitted(4)}


def test_P1_sensitivity_variant_is_declared_and_differs():
    """P1 (class-prioritised dispute) is a declared variant: a low-trust report does not
    dispute a trusted one unless corroborated from a second origin."""
    from functools import partial
    s = load_stream(os.path.join(ROOT, "revise_stream", "streams", "birthdate.json"))
    for fn in (oracle_v1.interpretations, oracle_v2.interpretations):
        g = all_gold(s, partial(fn, policy="P1"))
        # tau=4: wiki+mirror share one origin and rank below the registry -> cannot dispute it
        assert g["q_bd_t4"]["status"] == "established" and g["q_bd_t4"]["assertion"] == "1990-04-03"
        # tau=7: the forum is a second origin for the wiki's date -> corroborated -> dispute reopens even under P1
        assert g["q_bd_t7"]["status"] == "unresolved"
        # citizenship: a lone low-trust report cannot dispute the (standard) self-corrected value
        assert g["q_cit_t11"]["status"] == "established" and g["q_cit_t11"]["assertion"] == "nepal"
    # both oracles agree under P1 on every stream and belief time
    for path in STREAMS:
        s = load_stream(path)
        for tau in sorted({o.t_rep for o in s.observations}):
            assert oracle_v1.interpretations(s, tau, "P1") == oracle_v2.interpretations(s, tau, "P1"), (path, tau)
    # and P0 is the default
    s = load_stream(os.path.join(ROOT, "revise_stream", "streams", "birthdate.json"))
    assert all_gold(s, oracle_v2.interpretations)["q_bd_t4"]["status"] == "unresolved"


def test_factored_gold_equals_brute_force_gold():
    """gold_for restricts the oracle to the keys a query can depend on; the brute-force
    oracle projected onto the same keys must give identical gold."""
    for path in STREAMS:
        s = load_stream(path)
        assert all_gold(s, oracle_v1.interpretations) == all_gold(s, oracle_v2.interpretations)
