# PALIMPSEST pre-registration — v1 (frozen 3 Oct 2026 before the Setting 2 paid run) with outcomes

Freeze condition: this file is tagged `prereg-v1` in git before any Setting 2 (paid) run. Items marked **[open]** must be settled before the tag. Everything else is fixed as written in the plan (v0.3) and the semantics note (v0.1).

## Hypotheses

**H1 (primary, RQ2).** In Setting 2 (natural-language streams, automatically extracted dependencies), on *warranted-retraction consequence queries* (SEMANTICS §9: gold `established` at τ and different from gold at τ−1, after a retraction), PALIMPSEST's exact-match accuracy exceeds the append-only log + query-time adjudication baseline's by ≥ 10 percentage points at matched total cost, with the 95% stream-level cluster-bootstrap CI of the paired per-stream difference excluding zero. Unresolved queries are excluded by construction.

Falsification: if the CI includes zero under extracted dependencies (Setting 2), unfamiliar sources (Setting 3) and matched cost together, we report the negative result and the cost-crossover analysis as the main finding.

**H2 (RQ1).** A cost crossover exists: there is a query-to-update ratio r* < 1.0 above which write-time maintenance is cheaper than query-time adjudication at equal accuracy.

**H3 (RQ3).** PALIMPSEST's claim-level support has lower ECE and Brier than verbalized confidence on held-out sources and domains; risk–coverage dominates at coverage ≥ 0.5.

**H4 (ambiguity, joint).** PALIMPSEST's premature-commitment rate on unresolved queries is lower than the log baseline's, **and** its resolvable-query exact accuracy is not lower by more than 3 points. Either part failing fails H4.

Secondary hypotheses H2–H4 use Holm correction over the family of three.

## Endpoints and their definitions

| Endpoint | Definition | Queries |
|---|---|---|
| Primary | exact-match accuracy (eval/scorer.py `exact`) | warranted-retraction consequence queries on **downstream (derived) slots**, Setting 2 |
| Direct warranted accuracy | exact on warranted queries on the retracted key itself (ordinary updating) | secondary |
| Premature commitment rate | share of unresolved/possible-gold queries with `committed = 1` | all unresolved/possible, Settings 1–3 |
| Unsupported propagation rate | share of downstream queries whose answer changed after a non-warranted retraction event | tagged `retraction_consequence`, not warranted |
| Resolvable accuracy | exact on established-gold queries | all established |
| Calibration | Brier, ECE (15 equal-mass bins), risk–coverage AURC | claim-level support, Settings 2–3 held-out sources |
| Cost | input tokens + 8 × output tokens, summed over ingestion, repair and answering | per stream |
| Provenance | precision / recall against supporting observations | all but `reported` |
| Malformed rate | share of answers failing validation after one repair | all |

Stream is the unit of analysis; 10,000-resample cluster bootstrap; paired per-stream differences; effect sizes with CIs. Setting 3 (30 streams) is reported as transfer evidence, not tested.

## Fixed design choices

- Semantics: docs/SEMANTICS.md v0.2, dispute semantics **P0c with A-SELF** (decided 2 Oct 2026: a change cue identifies the operator; corrections remain disputes). Literal **P0** and **P0cc** are declared variants reported in Setting 1 only. **P1** (class-prioritised dispute with corroboration) is run in Setting 1 only as a sensitivity analysis and reported alongside; no hypothesis is tested under P1.
- Query selection (declared, deterministic given the generator seed): per stream, 40 primary queries = 30% warranted event queries (downstream first), 30% non-warranted event queries, 40% bitemporal-grid queries balanced between resolvable and unresolved; every event query keeps its τ−1 companion for the unsupported-propagation endpoint. `reported` slots are scored separately and excluded from the strata.
- Warranted-query floor: the Setting 2 evaluation set must contain on average ≥ 8 warranted-retraction consequence queries **on downstream slots** per stream (Setting 1, 500 streams: 8.0) (Setting 1 gate reports the empirical count). The generator's rates of explicit retraction and self-correction are fixed before the evaluation set is frozen and are not tuned afterwards. If the floor is not met, the stream length or the retraction rate is raised *before* the `evalset-v1` tag and the change is recorded here.
- Output contract: contract/answer.schema.json, contract/shared_prompt.md, contract/repair_prompt.md, identical for all systems; one repair attempt; malformed counts as wrong.
- Backbone: GPT-5 mini (Batch API) for all systems; Claude Haiku 4.5 (Batch) on a 20% Setting 2 subset as a sign-stability check only.
- Source priors: **class-level** (trusted/standard/low) learned priors as the main configuration; per-source priors as an ablation (motivated by the record-count argument in Nous 2610.00094).
- Baselines run: append-only log (full log, and top-k by recency+relevance for matched cost), rule-based bitemporal DB, always-abstain, always-commit; Graphiti-style graph only if ≤ $3; CUPMem/Kumiho/Nous as reported numbers only.
- Ablations: no dependency retraction; verbalized confidence; ignore source origin; collapse valid/belief time; gold vs extracted dependencies.
- Evaluation set freeze: Setting 2 paraphrases pass the cue-recovery check (deterministic + GPT-5 nano), ≤ 2 regenerations, author adjudication, oracle re-run on adjudicated text; then `evalset-v1` tag. No change to queries or gold after the tag.
- Dev split: 5 structured streams and their paraphrases, never used for evaluation.

## Power

150 Setting 2 streams; assumed SD of paired per-stream differences 0.20 → 95% CI half-width ≈ 0.032; 10-point effect detectable with margin. **[open: replace the assumed SD with the empirical SD of the paired per-stream difference (propagation on − off) from the Setting 1 run, recorded in docs/PHASE1_RESULTS.md, before the tag.]**

## What will be reported regardless of outcome

All endpoints for all systems and ablations; the accuracy–cost curves at ratios 0.1, 0.33, 1.0; extractor slot error, missed-ambiguity and spurious-ambiguity rates; malformed rates; measured (not estimated) token costs; every negative result.

## Deviations

Any deviation after the tag is recorded here with date and reason and reported in the paper.


## Outcomes (3 Oct 2026)

| Hypothesis | Result | Verdict |
|---|---|---|
| H1 (primary) | PALIMPSEST 0.953 vs claims-log LLM adjudicator 0.514 on warranted downstream queries; paired +43.9 [38.7, 49.3], n=99 streams | **supported** |
| H2 (crossover) | r* = 0.22 queries/observation for the raw-report log; the claims log is dearer than PALIMPSEST at any query load; no accuracy crossover | supported (cost only) |
| H3 (calibration) | support on extracted claims ECE 0.150 vs verbalised 0.088 vs sampling 0.073 | **not supported** |
| H4 (joint) | commit rate 0.082 vs 0.572; resolvable 0.975 vs 0.666 | supported |
| Sign stability (Sonnet 4.6, 15 streams) | +18.7 [7.5, 33.1] | sign holds |
| Setting 3 transfer (Wikidata, 30 streams; descriptive) | PALIMPSEST 0.923 = rule adjudicator on warranted downstream (24 queries, 13 streams); propagation +19.9 [2.6, 41.0]; LLM adjudicator 0.019 (0.077 excluding two output conventions) | transfers; LLM gap decomposed, not netted out |
| LongMemEval knowledge-update (78 items; external check) | last-write-wins 0.526, PALIMPSEST 0.167 (coverage 0.32), LLM adjudicator 0.359; exploratory self-update variant 0.474 | scoring-target mismatch (recency convention) |

## Deviations (dated)
- 3 Oct 2026: backbone changed from GPT-5 mini to Claude Haiku 4.5 (Message Batches, prompt caching), stronger check Claude Sonnet 4.6; environment forced (no other API reachable).
- 3 Oct 2026: Setting 2 on 100 streams (not 150); raw-report log and top-40 matched-cost variant on 30 streams; budget.
- 3 Oct 2026: frozen evaluation set has 7.41 warranted downstream queries per stream (floor was 8); not adjusted after the freeze.
- 3 Oct 2026: Setting 3 (Wikidata) and LongMemEval not run at the time of the v0.2 draft (no network path to download data from the workspace). Correction, same day: no per-entity Wikidata requests had been queued, only the selection query; the download chain is now `scripts/s3_fetch.py` (standard library, run by the author). The LongMemEval oracle file was downloaded by the author from the `longmemeval-cleaned` release (the original path 404s); the check is run with Claude Haiku 4.5 as backbone, extractor, question mapper and judge (not GPT-5 nano / Nova as first planned).
- 3 Oct 2026 (later): Setting 3 built from the author's fetch (40 persons, 128 organisations); schema decision recorded in docs/SETTING3.md (employer as stable affiliation set, after two mappings left the derived slot unresolved). LongMemEval adapter gained a key-canonicalisation pass after a first run (results_v1_nomerge.json kept); abstention credited on the six `_abs` items; an exploratory self-update variant added after seeing the result. Contract clarified (empty-set convention) after the runs; not re-run.
- Total measured LLM spend: $66.61 (ledger).

## Addendum A (3 Oct 2026, written before implementation): self-update default (A-SU) and the regime table

**Motivation (from the LongMemEval result and the regime table).** The regime table (`scripts/regime_table.py`, Setting 1, free) shows that last-write-wins by report time is right against the hidden world on 92% of value queries whenever the latest report is true (self-update, multi-source update, stale-earlier regimes: 3,930 of 6,765 queries), and PALIMPSEST under P0c abstains on 20–45% of those; in the delayed-report and erroneous-latest regimes recency is right on 4–8% and PALIMPSEST abstains on 65–92%. The LongMemEval result (44 of 69 items unresolved) is the single-source case of the same gap. The reviewer's point stands: a later uncued value from the *same origin* on a changeable attribute is, under symmetric error rates, more likely a change than an error (P(later current | values differ) = [c(1−e)² + e(1−e)(1−c)] / [c(1−e)² + 2e(1−e)(1−c)] ≥ ½ for any c > 0, e < ½), and the semantics has no rule for it.

**Rule A-SU (declared variant P0cSU).** On a single-valued, changeable key, an admitted report o may not be labelled ERR when every accepted competitor of o is a strictly-earlier report from o's own origin and no accepted correction targets o. In words: a source's later value supersedes its own earlier value; it is not a dispute. A-SU does not apply to stable attributes (a same-origin contradiction on a stable attribute stays a correction-or-error case), does not apply across origins (where class and corroboration still decide nothing under P0c), and never defeats a later competitor, a correction or a withdrawal. Attribute dynamics (`monotone`) are *not* added: they would require the extractor to label dynamics, and a monotone later value is already covered by A-SU when it comes from the same origin.

**Predictions (fixed before running; fresh streams, seeds 20000–20199, default GenConfig, never used before).**
- P-A1 (benefit). In the self-update regime, P0cSU abstention ≤ 0.05 (P0c on Setting 1: 0.20) and world accuracy within 2 points of last-write-wins by report time (0.92).
- P-A2 (cost bound). In the delayed-report, low-trust-error and other-error regimes, P0cSU's wrong-commit rate exceeds P0c's by at most 5 points (A-SU fires only on same-origin pairs, which are a minority of those regimes). If it exceeds 10 points in any of them, A-SU is reported as not adopted.
- P-A3 (no effect on the primary endpoint). On the fresh streams, warranted-downstream exact accuracy of P0cSU is within 2 points of P0c (A-SU does not touch retraction consequences), and the propagation effect is unchanged in sign and within its CI.
- P-A4 (LongMemEval, already seen, not a test). P0cSU reproduces the exploratory self-update variant (0.474, coverage 0.74) up to adapter noise; reported as confirmation of mechanism only.
Decision rule: A-SU is adopted as the default policy for self-report streams, and reported as a declared variant elsewhere, iff P-A1, P-A2 and P-A3 all hold; otherwise P0c remains the only policy and the regime table is reported as the limitation.

**Also pre-specified here, no LLM spend:** graded commitment (support-argmax on unresolved value slots) with a risk–coverage curve against last-write-wins on the disputed queries of Setting 1 and of LongMemEval; the regime table on Setting 1 (500 streams) and on 60 poisoning streams (rate 0.2, low channel, seeds 5000–5059). These are descriptive.

### Addendum A — outcomes (3 Oct 2026, fresh streams seeds 20000–20199, 200 streams, 13,448 current-slot single-valued queries)
- P-A1: self-update regime (n=53): abstention 0.321 → 0.000; world accuracy 0.679 → 0.962 = last-write-wins 0.962. **Holds.**
- P-A2: wrong-commit, P0c → P0cSU: delayed-report 0.267 → 0.280 (+1.3 pts), low-trust-error 0.042 → 0.052 (+1.0), other-error 0.083 → 0.083 (0). **Holds** (all ≤ 5 points).
- P-A3: warranted-downstream exact accuracy 1.000 under both policies' own gold; propagation effect +20.4 [17.9, 22.9] (P0c) vs +21.0 [18.3, 23.7] (P0cSU), 199 streams; warranted downstream per stream 7.70 vs 7.66. **Holds.**
- P-A4 (already seen): LongMemEval P0cSU reproduces the exploratory variant (0.474 / coverage 0.74) — mechanism confirmed, not a test.
Decision rule satisfied: A-SU adopted as the default for self-report streams and reported as declared variant P0cSU elsewhere; P0c remains the policy of the frozen Settings 1–3 results (not re-scored).
Graded commitment (support-argmax, Setting 1, 2,279 disputed queries): world accuracy at full coverage 0.593 vs last-write-wins 0.614 on the same queries; at 49% coverage 0.690 vs 0.638. Per regime, argmax beats recency where the latest report is wrong (delayed 0.49 vs 0.08; low-trust error 0.61 vs 0.04) and loses where it is right (stale-earlier 0.81 vs 0.92). Poisoning regime (60 attack streams, 78 queries where the latest report is an injection): P0c commits to the injected value on 76%, recency on 95%; argmax 0.21 world accuracy.

## Deviations and additions after the second external review (3 Oct 2026, evening)
- **Incremental store bug fixed (post hoc, disclosed).** 18 of 6,737 Setting 2 answers differed between the incremental store and symbolic replay on identical extracted claims (0 in Setting 3). All 18: an extracted correction whose entity/value were swapped by the extractor landed on another key than its target; replay applied the same-origin withdrawal (A-SELF) globally, the store only on the correction's own key. Fixed in `palimpsest/core.py`; structured systems re-scored from cached extractions (`scripts/rescore_structured.py`; previous results kept as `_results.prev.json`). Effect: Setting 2 PALIMPSEST warranted downstream 0.953 → 0.956 (= replay); H1 paired difference +43.9 → +44.2 [39.0, 49.6]; disagreements now 0 in Settings 2, 3 and the Sonnet subset.
- **Transition table (reviewer P0-5)** from cached answers (`scripts/transitions.py`): on the 538 non-warranted event pairs of Setting 2, correct→wrong is 0.007 for PALIMPSEST and 0.076 for the LLM adjudicator; the registered "unsupported propagation" (renamed *answer instability under unchanged gold*) is 0.032 vs 0.383, and 0.669 of the adjudicator's pairs are wrong→wrong. The harm claim rests on correct→wrong from now on.
- **Primary-endpoint share of convention-affected queries (P0-3 diagnostic):** 23 of 795 warranted downstream queries in Setting 2 have empty-set gold (3 of 24 in Setting 3); LLM adjudicator micro exact 0.513 with them, 0.528 without; PALIMPSEST 0.940 / 0.938. The headline difference is not driven by the convention.
- **Systems benchmark (P0-1, Stage C; `scripts/systems_bench.py`, free):** incremental maintenance vs cold symbolic replay vs cached replay on 60 Setting 1 streams at query/observation ratios 0.1, 0.33, 1, 3 and a scale sweep (reports per key 7/10/13, horizon 60/120/240 days). Answers identical on all 36,332 + 4,698 queries. Total CPU: replay cheaper at r ≤ 1 at default scale (r = 1: 0.32 s vs 0.36 s per stream), incremental cheaper at r = 3 (0.46 s vs 0.93 s) and at r = 1 with longer horizons (240 days: 0.79 s vs 1.38 s) or 10 reports per key; with 13 reports per key the per-write enumeration dominates (3.72 s vs 1.66 s, peak memory 22 MB vs 4 MB). Query latency: incremental 0.3–1.3 ms mean, p95 ≤ 7 ms, max 215 ms; replay 2.0–15.7 ms mean, p95 up to 91 ms, max 2.6 s. Conclusion for the subtitle: write-time maintenance buys bounded query latency and identical answers; it saves total work only when queries are at least as frequent as observations or histories are long, and its write cost grows exponentially in reports per key.
- **Amended-contract reruns (3 Oct 2026, night; $22.23):** Setting 2, first 30 streams, Haiku 4.5: PALIMPSEST 0.989 on the subset; original-protocol adjudicator 0.408 (paired +58.2 [50.5, 66.3]); amended-contract adjudicator 0.400 (+59.0 [51.4, 66.5]), resolvable 0.607, commit 0.533; context budget k=10/20/40/full: 0.225 / 0.385 / 0.429 / 0.400 at 399k / 424k / 464k / 552k weighted tokens per stream vs 188k for PALIMPSEST; raw-report adjudicator 0.323 at 448k. Setting 3 (30 streams): amended adjudicator 0.019 warranted downstream (unchanged), resolvable 0.205 (from 0.185); raw-report 0.173 (from 0.077). The missing convention explains little; H1's matched-cost clause is reported as not executable as registered (every budget costs more than extraction alone and scores lower).
- **Claims narrowed in v0.4 (done):** "write-time beats query-time" → "symbolic justification maintenance under a declared uncertainty policy vs the evaluated LLM adjudicators, with identical answers to symbolic replay and the measured latency/work trade-off above"; "automatically extracted dependencies" → "automatically extracted assertions under a fixed, declared rule schema"; "no public STALE release" → dated statement (a repository is reported public by the reviewer; not evaluated for budget/context reasons unless cloned).

## After the v0.4 external review (3 Oct 2026, late) — correctness and consistency pass, no LLM spend
- **Oracle factorisation validated** (`scripts/oracle_validation.py`): per-key gold vs brute-force global enumeration over each query's dependency closure on 303 streams, 21,825 value queries (10,847 derived): 0 disagreements; product structure |global| = ∏ per-key held on all 21,825 checks; closure independence held on all. The Appendix A sentence claiming possible over-generation was wrong and is withdrawn; the exactness conditions (same-key admissibility relations; each key at most once per derivation path) are stated.
- **Self-update formula corrected**: binary model P = [c(1−e)² + (1−c)e(1−e)] / [c((1−e)²+e²) + 2(1−c)e(1−e)] (≥ ½ iff e ≤ ½); open-value model P = [c(1−e) + (1−c)e(1−e)] / [c + (1−c)(2e−e²)] (> ½ iff c(1−2e) ≥ (1−c)e(1−e)). Earlier formula omitted the c·e² term. Stated as a preference argument, not a justification; A-SU remains a declared policy.
- **A-SU trade-off stated everywhere** (intro, §8.3, conclusion): wrong commitments +1.3 / +1.0 / +0.0 points in the delayed / low-trust / other-error regimes; regime table now paired on the 200 fresh streams (P0c vs P0cSU, same queries); Setting 1 table moved to the appendix.
- **Poisoning reported as attack-success events**: when the latest report is an injection, P0c commits to the injected value on 78% (abstains 22%), last-write-wins on 100%, support-argmax on 82%; world accuracy no longer used for this comparison.
- **Clipped tables fixed** (Tables 5, 7): instability column dropped from the NL tables (in the transition table instead), shorter names, footnotesize; bbox check finds no content outside any page.
- **Claims qualified**: "bounded latency" → "lower measured latency"; "identical answers" → status, assertion and alternatives identical on every query; provenance lists differ on 2.3% (Setting 2) / 5.3% (Setting 3); abstract count = 40,030 (macro).
- **Holm correction computed** (`scripts/holm_tests.py`, 10,000 stream-level resamples, one-sided): H2 p<1e-4 (r* = 0.229 [0.224, 0.233]); H3 p = 0.998 (ECE difference +0.062 [0.015, 0.078]); H4a p<1e-4 (commit −0.492), H4b p<1e-4 (resolvable +0.310 vs margin −0.03); Holm-adjusted: H2, H4 rejected, H3 not.
- Reliability diagrams added (Appendix B); StateMemBench reference corrected to Fan et al., arXiv:2608.19652 (author list to complete); DOI remains a placeholder until the Zenodo deposit.

## After the full v0.4 review text (3 Oct 2026, night) — second consistency pass, no LLM spend
- **Gold mismatch found in three post-hoc scripts.** `transitions.py`, the LLM error taxonomy and the convention breakdown had scored against the pre-adjudication gold files (`data/setting2_100/*.gold.json`) instead of the frozen gold the pipeline scores against (`data/s2/<sid>/frozen.json`; 274 of 6,737 entries differ). Recomputed: non-warranted event pairs 587 (not 538); PALIMPSEST instability 0.092 (macro 0.083 in Table 5), correct→wrong 0.063 (35 of 37 such pairs have a mis-extracted report at the event time); LLM adjudicator instability 0.404, correct→wrong 0.080, wrong→correct 0.032, wrong→wrong 0.681. **The earlier harm numbers 0.007 vs 0.076 are withdrawn.** Primary endpoint 741 queries (7.41/stream), 21 with empty-set gold; LLM micro 0.525 / 0.540 without them. Taxonomy over 4,062 primary answers: correct 47.7, premature 15.7, under-commit 9.8 (+1.0 absent), wrong alternative set 8.2, wrong value 6.0, gold-unknown answered 6.5, unknown-on-established 1.6, conventions 3.0 (exclusive categories).
- **Oracle exactness scoped and tested**: static condition (rule-body attribute closures pairwise disjoint) passes every released domain; the reviewer's shared-ancestor domain fails it and the per-key procedure over-generates there exactly as predicted (`oracle_validation.py` counter-example: per-key {A, B, ∅} vs global {A, B}). Full validation unchanged: 21,825 queries, 0 disagreements.
- Equivalence inventory stated per setting (30,272 / 6,737 / 714 / 994 / 40,030 queries; 0 disagreements on status, assertion, alternatives; provenance differs 2.3% / 5.3%). Systems-benchmark method stated (2-vCPU container, process_time, single runs, tracemalloc peak ≠ RSS; cached replay = never-invalidated memo keyed by key/belief time). Crossover stated as workload-dependent (interpolated ≈1.1 at default scale).
- H2 restored as the LLM-token crossover r* = 0.229 [0.224, 0.233] (separate from the CPU crossover). Query-count flow stated (Setting 1: 60.5/stream = 37.1 primary + 20.5 companions + 2.9 reported; 16,683 = primary with non-unknown gold; Setting 2: 6,737 = 4,062 + 2,337 + 338; 741 warranted downstream). "A tenth" → "a seventh". Table 1 cells relabelled (yes / n.r.) with criteria; StateMem added (Fan et al. 2026). Decision table for unknown/empty/false added and verified on toy streams. A-CHG's ENDED clause and inertia-for-`at` stated in §3. Lenient scores declared not reported; malformed 0, repairs 1 (Haiku) and 192/994 (Sonnet). Original contract archived as `contract/shared_prompt_original.md`. Abstract labels original-protocol vs amended-protocol estimates. Phrases flagged by the reviewer removed.

## Semantic clarification found during re-implementation (5 Oct 2026, no LLM spend, no result changed)
- **Retracted corrections keep their withdrawing effect.** While re-implementing the semantics in the `palimem` SDK (differential harness against the frozen gold, 500 streams, 30,272 queries), the following property of the deposited oracle was made explicit: a `correct` report that is itself later retracted still withdraws its target. The frozen sets contain 387 such retracted corrections; requiring the acting report to be live at evaluation time changes 84 of 314 comparable streams. The deposited code, the frozen gold and every number in the paper use the former rule; it is now named `acting_reports_must_be_live = false` and is the rule the SDK's `revise-stream-v1` compatibility profile fixes. The product semantics of the SDK may choose otherwise; the paper's claims are unaffected. Also made explicit: the deposited code applies inertia to every attribute (not only single-valued changeable ones), and a source-level retraction removes assertions made by that source after the retraction as well as before (106 streams, 241 assertions). Under these three rules the SDK reproduces the frozen gold exactly (0 disagreements).
