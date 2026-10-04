"""Phase 1 unit tests: generator determinism and invariants, PALIMPSEST core agreement
with the oracle (propagation on) and divergence (propagation off), metrics."""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from baselines.references import always_abstain, always_commit  # noqa: E402
from eval.metrics import bootstrap_paired, stream_metrics  # noqa: E402
from eval.scorer import score  # noqa: E402
from palimpsest.core import BeliefStore  # noqa: E402
from revise_stream import oracle_v1  # noqa: E402
from revise_stream.generator import GenConfig, generate, select_queries  # noqa: E402
from revise_stream.gold import all_gold  # noqa: E402
from revise_stream.model import load_stream, stream_from_dict  # noqa: E402


def _stream(seed):
    d, hidden = generate(seed)
    s = stream_from_dict(d)
    gold = all_gold(s, oracle_v1.interpretations)
    keep = set(select_queries(s, gold, GenConfig().n_queries, random.Random(seed)))
    s.queries = [q for q in s.queries if q.id in keep]
    gold = {k: v for k, v in gold.items() if k in keep}
    return s, gold, hidden


def test_generator_is_deterministic():
    a, _ = generate(7)
    b, _ = generate(7)
    assert a == b


def test_generator_invariants():
    for seed in range(5):
        d, hidden = generate(seed)
        s = stream_from_dict(d)
        ts = [o.t_rep for o in s.observations]
        assert ts == sorted(ts)                                  # belief time is arrival order
        from collections import Counter
        c = Counter(o.key for o in s.observations if o.kind == "assert")
        assert max(c.values()) <= GenConfig().max_obs_per_key
        # every admitted key has at least one admissible interpretation at every belief time
        for tau in sorted(set(ts)):
            for key in s.admitted_by_key(tau):
                assert oracle_v1.key_interpretations(s, tau, key), (seed, tau, key)
        # hidden truth labels exist for every assertion and the world is never exposed
        assert set(hidden["truth"]) == {o.id for o in s.observations if o.kind == "assert"}
        assert "_world" not in d and "_truth" not in d


def test_every_event_query_has_pre_companion_and_pairs_are_kept():
    s, gold, _ = _stream(3)
    pres = {(q.entity, q.attr, q.slot, q.tau) for q in s.queries if "pre" in q.tags}
    for q in s.queries:
        if "event" in q.tags and q.slot in ("current", "downstream"):
            assert (q.entity, q.attr, q.slot, q.tau - 1) in pres


def test_store_with_propagation_matches_oracle_and_without_diverges():
    worse_somewhere = False
    for seed in range(6):
        s, gold, _ = _stream(seed)
        qs = sorted(s.queries, key=lambda q: (q.tau, q.id))
        on, off = BeliefStore(s, propagation="on"), BeliefStore(s, propagation="off")
        a_on = {q.id: on.answer(q) for q in qs}
        a_off = {q.id: off.answer(q) for q in qs}
        sc_on = {q.id: score(a_on[q.id], gold[q.id], s, q) for q in qs}
        sc_off = {q.id: score(a_off[q.id], gold[q.id], s, q) for q in qs}
        m_on = stream_metrics(s, a_on, gold, sc_on)
        m_off = stream_metrics(s, a_off, gold, sc_off)
        assert all(v["exact"] == 1 for v in sc_on.values()), [k for k, v in sc_on.items() if v["exact"] == 0][:5]
        assert m_on["malformed_rate"] == 0
        if m_off["warranted_acc"] is not None and m_on["warranted_acc"] is not None:
            worse_somewhere |= m_off["warranted_acc"] < m_on["warranted_acc"]
    assert worse_somewhere


def test_forced_commit_commits():
    s, gold, _ = _stream(1)
    qs = sorted(s.queries, key=lambda q: (q.tau, q.id))
    st = BeliefStore(s, commit=True)
    ans = {q.id: st.answer(q) for q in qs}
    sc = {q.id: score(ans[q.id], gold[q.id], s, q) for q in qs}
    m = stream_metrics(s, ans, gold, sc)
    assert m["commit_rate"] is not None and m["commit_rate"] > 0.5
    assert m["resolvable_acc"] == 1.0


def test_bootstrap_paired():
    (d, lo, hi), n = bootstrap_paired([1, 1, 1, 0.5], [0.5, 0.5, 0.5, 0.5], n_boot=500)
    assert n == 4 and abs(d - 0.375) < 1e-9 and lo <= d <= hi


def test_no_relaxation_on_hand_streams_and_generated_dev():
    import glob
    for path in glob.glob(os.path.join(ROOT, "revise_stream", "streams", "*.json")):
        s = load_stream(path)
        for tau in sorted({o.t_rep for o in s.observations}):
            for key in s.admitted_by_key(tau):
                oracle_v1.key_interpretations(s, tau, key)
        assert not s._cache.get("_relax"), path
    for seed in range(3):
        d, _ = generate(seed); s = stream_from_dict(d)
        for tau in sorted({o.t_rep for o in s.observations}):
            for key in s.admitted_by_key(tau):
                oracle_v1.key_interpretations(s, tau, key)
        assert not s._cache.get("_relax")
