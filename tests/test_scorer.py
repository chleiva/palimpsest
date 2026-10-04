import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eval.scorer import score, validate  # noqa: E402
from revise_stream import oracle_v2  # noqa: E402
from revise_stream.gold import all_gold  # noqa: E402
from revise_stream.model import load_stream  # noqa: E402

ALEX = os.path.join(ROOT, "revise_stream", "streams", "alex.json")


def _ans(**kw):
    base = {"query_id": "q", "status": "unknown", "assertion": None, "alternatives": [], "provenance": []}
    base.update(kw)
    return base


def test_schema_validation():
    assert validate(_ans()) is None
    assert validate(_ans(status="maybe")) is not None
    assert validate({"status": "unknown"}) is not None
    assert validate(_ans(provenance=["o1", "o1"])) is not None


def test_exact_unresolved_requires_full_alternative_set_and_no_selection():
    s = load_stream(ALEX)
    g = all_gold(s, oracle_v2.interpretations)
    q = next(x for x in s.queries if x.id == "q_current")
    full = [["london"], ["paris"], ["london", "paris"]]
    r = score(_ans(status="unresolved", alternatives=full, provenance=["o1", "o2"]), g[q.id], s, q)
    assert r["exact"] == 1 and r["committed"] == 0 and r["prov_precision"] == 1.0 and r["prov_recall"] == 1.0
    # superset: lenient only
    r = score(_ans(status="unresolved", alternatives=full + [None]), g[q.id], s, q)
    assert r["exact"] == 0 and r["lenient"] == 1
    # order and case do not matter
    r = score(_ans(status="unresolved", alternatives=[["Paris", "London"], ["paris"], ["london"]]), g[q.id], s, q)
    assert r["exact"] == 1
    # premature commitment: picking Paris
    r = score(_ans(status="established", assertion=["paris"], provenance=["o2"]), g[q.id], s, q)
    assert r["exact"] == 0 and r["committed"] == 1
    # 'possible' with a selected value on a value slot is still commitment
    r = score(_ans(status="possible", assertion=["paris"]), g[q.id], s, q)
    assert r["exact"] == 0 and r["committed"] == 1


def test_possible_and_established_yesno():
    s = load_stream(ALEX)
    g = all_gold(s, oracle_v2.interpretations)
    q = next(x for x in s.queries if x.id == "q_move")
    assert score(_ans(status="possible", assertion=True), g[q.id], s, q)["exact"] == 1
    r = score(_ans(status="established", assertion=True), g[q.id], s, q)
    assert r["exact"] == 0 and r["committed"] == 1
    r = score(_ans(status="established", assertion=False), g[q.id], s, q)
    assert r["exact"] == 0 and r["committed"] == 1


def test_provenance_validated_for_support_not_existence():
    s = load_stream(ALEX)
    g = all_gold(s, oracle_v2.interpretations)
    q = next(x for x in s.queries if x.id == "q_current_tau1")
    r = score(_ans(status="established", assertion=["london"], provenance=["o1", "o2"]), g[q.id], s, q)
    # o2 exists in the stream but is not admitted at tau=1, so it does not support
    assert r["exact"] == 1 and r["prov_precision"] == 0.5 and r["prov_recall"] == 1.0


def test_malformed_is_wrong_not_abstention():
    s = load_stream(ALEX)
    g = all_gold(s, oracle_v2.interpretations)
    q = next(x for x in s.queries if x.id == "q_current")
    r = score({"status": "unresolved"}, g[q.id], s, q)
    assert r["malformed"] == 1 and r["exact"] == 0 and r["lenient"] == 0
