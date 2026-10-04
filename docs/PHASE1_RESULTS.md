# Phase 1 results — Setting 1 (structured streams, gold dependencies, no LLM)

> **Superseded numbers.** The figures below are from the first run (generator v0.1). After a generator fix (temporal cues only on changeable attributes) all Setting 1 data were regenerated under generator v0.2 and every experiment rerun; the current numbers are in `data/setting1_results.json`, `data/setting1_P0_results.json`, `data/setting1_P1_results.json`, `data/rq3_setting1.json`, `data/poison_setting1.json`, rendered by `scripts/make_tables.py` into `paper/tables/`. Headline changes: propagation on−off +20.6 [18.7, 22.4] (was +20.4); forced-commit unsupported propagation +9.0 [7.8, 10.2] (was +8.0); downstream warranted queries 7.42/stream (was 7.66). Conclusions unchanged.


Run: 2 Oct 2026, 500 generated streams (`scripts/generate_streams.py 500 data/setting1`, generator v0.1, seeds 0–499), all systems (`scripts/run_setting1.py`), semantics v0.3 (P0c + A-SELF), output contract v0.1, scorer v0.1. Mean 131 observations and 60.6 queries per stream (40 primary + τ−1 companions). Everything here is free of LLM cost; the purpose is to validate that the benchmark discriminates and that the write-time store is correct, not to test H1 (which is a Setting 2 hypothesis).

## Phase 1 gate (plan §7)

| Part | Requirement | Result (stream-level bootstrap 95% CI) | |
|---|---|---|---|
| (a) | propagation-off PALIMPSEST scores measurably worse on warranted downstream queries | on − off = **+0.204 [+0.186, +0.222]**, n = 495 streams with ≥1 such query | PASS |
| (b) | always-abstain good on unresolved, poor on resolvable; always-commit the reverse | abstain: resolvable 0.000 / unresolved 0.374; commit: resolvable 0.766 / unresolved 0.000 | PASS |
| (c) | forced-commit variant shows a measurable rise in unsupported propagation | commit − PALIMPSEST = **+0.080 [+0.069, +0.092]**, n = 500 | PASS |

## Endpoints by system (mean over streams, 95% CI)

| system | warranted downstream | warranted direct | resolvable | unresolved | commit rate | unsupported prop. |
|---|---|---|---|---|---|---|
| PALIMPSEST (propagation on) | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| PALIMPSEST, propagation off | 0.796 [0.78, 0.81] | 1.000 | 0.933 | 0.970 | 0.003 | 0.026 |
| PALIMPSEST, forced commit | 1.000 | 1.000 | 1.000 | 0.042 | 0.783 | 0.080 |
| append-only log, query-time (rule adjudicator) | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 |
| temporal DB (no justifications) | 0.815 [0.80, 0.83] | 0.903 | 0.909 | 0.000 | 0.849 | 0.102 |
| always-abstain | 0.000 | 0.000 | 0.000 | 0.374 | 0.000 | 0.088 |
| always-commit | 0.426 [0.41, 0.44] | 0.965 | 0.766 | 0.000 | 0.791 | 0.147 |

Cost (mean work units per stream): PALIMPSEST 132 key recomputations + 190 derived refreshes at write time, 61 lookups at read time; the query-time log scans 5,358 log entries and recomputes 126 keys per stream at read time. In Setting 1 both are exact, so the accuracy–cost comparison is degenerate by design; the crossover (RQ1) is a Setting 2 question where the adjudicator is an LLM.

## What the numbers mean, and what they do not

The write-time store with justification propagation reproduces the oracle exactly on every query (24,300 answers across 500 streams, zero errors, zero malformed), so the incremental maintenance is correct. Turning off retraction propagation costs 20 points on warranted downstream queries and nothing on direct ones, which is exactly the signature the hypothesis predicts: ordinary belief updating handles the retracted key, and only propagation handles its consequences. The forced-commit variant retains perfect resolvable accuracy while committing on 78% of unresolved slots and changing downstream answers after non-warranted events 8 points more often: premature commitment and unsupported propagation are measured as separate things and move independently of resolvable accuracy, as the design intended. The two references split cleanly, so abstention cannot pass as uncertainty handling.

These are validation results on a benchmark whose generator and system share an author (plan §8). They say the instruments work; they do not test H1, and the perfect scores say nothing about Setting 2, where extraction and LLM adjudication introduce the errors the study is about.

## Numbers carried into the pre-registration

- Empirical SD of the paired per-stream difference (propagation on − off) on warranted downstream accuracy: **0.210** (n = 495). With 150 Setting 2 streams the 95% CI half-width is ≈ 0.034, so a 10-point effect remains detectable with margin; the assumed 0.20 is replaced by 0.21.
- Warranted downstream queries per stream: 7.66 (5 of 500 streams have none), below the floor of 8 by a small margin after the A-CUE/A-CHG refinements. Checked on 60 streams: quota 35/25/40 alone gives 7.92; quota 35/25/40 with 44 primary queries per stream gives 8.02. The streams themselves contain ~23 warranted queries on average, so the floor is a selection-budget question, not a generator-rate question. Decision before the Setting 2 freeze: 44 primary queries with quota 35/25/40 (≈ 10% more answering cost, ≈ $2 at the primary backbone), recorded here as a pre-freeze adjustment; generator rates unchanged.
- Unsupported-propagation pairs per stream: 5.8.

## Semantics changes made during Phase 1 (all in SEMANTICS.md v0.3)

1. **A-CUE / policy P0c** (decided with the author): a change cue shields the cued report from *strictly earlier* competitors; same-time and later competitors still dispute it. Literal P0 left 2.3 warranted queries per stream and 48% unresolved slots.
2. **A-CHG** is a presupposition about the previous *value*, not about a particular report: if any earlier report of the previous value exists, at least one must be accepted. Forcing the latest such report TRUE made streams inconsistent when that report was erroneous.
3. **A-SELF** (same-origin correction withdraws the corrected report) and `competing_values` (per-attribute) from Phase 0 are unchanged.
4. Invariant now checked on every generated stream: every admitted key has at least one admissible interpretation at every belief time (500/500 streams).

## Known limitations of this run

- Provenance precision/recall use the Phase 0 scorer approximation (supporting = admitted observations on the key with a value in the gold answer; all body-attribute observations for derived slots). The derived-slot approximation is too broad, which is why PALIMPSEST's recall reads 0.62 despite exact answers. Replacing it with justification-path extraction is Phase 2 work; provenance numbers above are not interpretable yet.
- The temporal DB baseline is a minimal implementation (latest valid-time anchor wins, no error hypotheses).
- `until`/interval valid-time cues and negative-polarity assertions remain deferred.
- The P1 and literal-P0 sensitivity variants were not run on the 500 streams in this pass (both are implemented; the run is a one-line change to `run_setting1.py`).
