# PALIMPSEST — Research Execution Plan v0.3

Prepared 2 Oct 2026 (v0.3: ambiguity rule frozen, ATMS oracle, ambiguity endpoints, abstain/commit references, shared output contract §3.4) against the one-page proposal "PALIMPSEST: Accountable Belief Revision for LLM Systems" (C. Leiva Beltran, 2 Oct 2026). Constraints: total spend ≤ $100 (LLM + everything else); API access to Anthropic, OpenAI and AWS; MacBook M3 16 GB used only for deterministic code, never for local LLM inference; target is an arXiv preprint with no fixed deadline, written to survive later peer review.

## 1. Critical reading of the proposal

What I would defend as it stands. The falsification criterion is unusually honest: the append-only log with query-time adjudication is the right null, and committing to report a cost crossover rather than a blanket win is the correct framing. Scoring against *justified* belief rather than ground truth is the right choice, because an agent that believes a true thing for no good reason should not be rewarded. Separating support, extraction fidelity and answer correctness, and computing confidence intervals at the stream level, are both things reviewers will look for and rarely find.

What must be fixed before any experiment is run, because each one can invalidate the results after the money is spent:

1. The justified-belief oracle is undefined, and it is the whole evaluation. "The beliefs those observations justify" needs a formal reference reasoner that (a) sees only the observation stream and the declared source priors, never the world state, and (b) is not the system under test. Otherwise the benchmark scores PALIMPSEST against a mirror of itself. My recommendation: define the oracle as a rule-based justification-maintenance reasoner over a Datalog-like claim language with explicit contradiction relation and declared defeasible rules, with a fixed, published admission policy. PALIMPSEST's LLM-facing components are then measured by how closely they recover what the oracle derives.

**Frozen rule for ambiguous observations (decided 2 Oct 2026).** When the available observations and declared source assumptions do not uniquely determine a revision, the oracle retains the admissible interpretations. A system receives full credit when its answer preserves that uncertainty: it may assert conclusions supported under every admissible interpretation, but must qualify, present alternatives, or abstain on conclusions that differ between interpretations. Selecting one unsupported interpretation receives no full credit. No particular internal representation is required; the requirement is on observable behaviour, so that the scoring does not favour PALIMPSEST's hypothesis store over the append-only baseline.

Worked case: "Alex lives in Paris" after "Alex lives in London", with no further temporal or exclusivity information.

| Query | Expected behaviour |
|---|---|
| "Did Alex move from London to Paris?" | State that a move is possible but not established. |
| "Was the London report wrong?" | State that the evidence does not establish this. |
| "What locations have been reported?" | Report both, with their observation provenance. |
| "Should we retract a conclusion that depends on Alex having left London?" | Treat it as unresolved unless departure is independently supported. |

The admissible interpretations come from the declared benchmark semantics, not from every imaginable explanation: each claim type declares its finite menu of resolution operators (for residence: move, additional residence, erroneous earlier report, erroneous later report) together with cardinality and exclusivity assumptions. Source priors alone never silently supply missing timestamps or an assumption that a person has only one residence, and arrival order is never used as a proxy for valid-time order unless the semantics declare it.

Two consequences follow. First, the reference reasoner must retain alternative assumption sets, so it is an assumption-based truth-maintenance system (de Kleer-style ATMS over environments) rather than a single-state JTMS; a reasoner that selects one consistent state cannot supply this gold. Second, ambiguous cases are separated from the primary retraction endpoint: the ≥10-point hypothesis concerns consequences of retractions actually warranted by the observations, while ambiguous cases separately measure premature commitment and unsupported propagation (§4). Set-valued gold remains the representation of unresolved possibilities; "either operator is acceptable" is rejected.

2. "Matched compute" is not yet operational. The proposal counts extraction, verification, revision, graph maintenance, retrieval and answering, which is right, but write-time and query-time systems spend tokens at different moments. Define cost per stream as total input + output tokens (weighted by the backbone's price ratio, 1:8 for the planned backbone) summed over ingestion and answering, and report every result as a point on an accuracy–cost curve at three query-to-update ratios (0.1, 0.33, 1.0). "Matched" then means comparing at equal total cost by varying the log baseline's retrieval window and PALIMPSEST's verification budget, not asserting equality.

3. The baseline list is not affordable or reproducible as written. CUPMem has no released code as far as I can find; Kumiho is a commercial product whose paper (arXiv 2603.17244) releases no code and evaluates on LoCoMo, not on conflict streams; Nous and TOKI are preprints whose implementations I have not verified. Six external systems with matched backbones on $100 is not a plan. Prioritised list: (i) append-only log + query-time adjudication (the falsifier; must be strong, so it gets the most engineering attention after PALIMPSEST itself); (ii) rule-based bitemporal database without justifications (shows what retraction adds over plain temporal storage); (iii) a Graphiti/Zep-style temporal knowledge graph, re-implemented minimally from the paper's description with the same extractor, only if the open-source library runs with our backbone at low cost; (iv) CUPMem, Kumiho, Nous reported numbers only, on STALE where directly comparable, clearly labelled as not reproduced. Parametric editing is dropped from our runs; it is cited for context.

4. The primary outcome and the decision rule need numbers now, not after seeing results. See §5. Without this the "falsified if no gain" sentence is unfalsifiable in practice.

Smaller points. Source reliability as "a learned prior updated from verified outcomes" needs a clear statement of what counts as a verified outcome inside a stream, or it leaks ground truth. Privacy redaction versus epistemic supersession is a good distinction but is not tested anywhere; either add one small test or move it to discussion. The poisoning question should be explicitly secondary with its own small, pre-registered attacker model, otherwise reviewers will treat it as a security claim.

## 2. Scope decisions forced by the budget

Everything deterministic is free: the stream generator, the oracle, the belief store, the rule-based baselines, all metrics, and all five ablations except one run on replayed logs with no new LLM calls. The LLM is used in exactly four places: paraphrasing structured observations into natural language, extracting claims and dependencies from natural language, answering queries, and judging free-text answers on the two external benchmarks. Every LLM call goes through the Batch API (50% off) with a fixed system prompt eligible for prompt caching.

Backbone. One primary backbone for every system, GPT-5 mini via the Batch API ($0.125 input / $1.00 output per million tokens, verified 2 Oct 2026). A backbone-robustness check reruns 20% of the natural-language streams on Claude Haiku 4.5 Batch ($0.50 / $2.50). Prompt iteration during development uses GPT-5 nano Batch ($0.025 / $0.20) on a 5-stream dev split, never the evaluation split. AWS is not needed; if Bedrock is preferred over direct APIs for billing reasons the plan is unchanged.

Sizes. Setting 1 (structured): 500 streams, free, so sized for calibration statistics rather than cost. Setting 2 (natural language): 150 streams × 120 observations × 40 queries. Setting 3 (independently assembled realistic streams): 30 streams built from public revision data. External checks: STALE subsample of 100 scenarios (300 queries) stratified over its three probing dimensions, and ~80 LongMemEval knowledge-update items. Full STALE is not affordable: 1,200 queries × ~100K-token contexts on Haiku alone is about $120 for the log baseline, so we subsample and say so.

Dropped or deferred: CUPMem/Kumiho/Nous reproductions, parametric-editing runs, any local-model experiments, the general poisoning study beyond one explicit attacker model.

## 3. Design

### 3.1 REVISE-Stream generator (free, deterministic, seeded)

A small world simulator over entities and attributes typed as volatile or stable, with declared dependency rules (e.g. employer ⇒ work city with a defeasible exception list; role ⇒ permissions). Events change the world at times t; sources observe events with per-source delay distributions, reliability, correlation (shared upstream origin), and occasional false reports from otherwise reliable sources. Perturbations are sampled from a fixed menu: delayed report, unknown change date, reversal and re-reversal, correlated repetition, low-trust correction that is actually right, trusted source that is wrong, explicit retraction of a source. Every stream records three layers: world trajectory, observation sequence with provenance, and the oracle's justified-belief trajectory over belief time.

Queries are generated from templates over the four cells of the bitemporal grid (current, as-of-valid-time, as-of-belief-time, and "what changed when"), plus retraction-consequence queries that target downstream conclusions of retracted evidence. Each query carries its gold answer under every admissible interpretation; a query is *resolvable* when the answer agrees across interpretations and *unresolved* otherwise, and the generator stratifies both kinds over all query templates so that no template is a proxy for ambiguity. The generator also records which observations carry explicit timestamps and which claim-type resolution menu applies, so that the oracle's environments are derivable from the declared semantics alone.

Every system answers through one shared output schema: an assertion, a status in {established, possible, unresolved, unknown}, the alternatives it is holding open, and the provenance it relies on. The schema is the only representational commitment imposed, it applies identically to all baselines, and it is what makes "qualify, present alternatives, or abstain" machine-scorable without an LLM judge on Settings 1–3. The log baseline's prompt receives the same instruction to preserve uncertainty as PALIMPSEST's answerer.

Natural-language streams are produced by templating each observation, then an LLM paraphrase pass for surface variety, with a fidelity check that the paraphrase still entails the structured observation (checked by the extractor on a held-out sample; disagreement rate reported).

Setting 3 streams are assembled from public data with no LLM in the loop for construction: Wikipedia revision histories of infobox facts with reverts, Wikidata statement histories with end-dates and deprecated ranks, and published newspaper correction notices paired with the original articles. Conflict labels and source reliabilities are hidden from all systems and used only for scoring. This is the transfer test and the only part of the benchmark that is not of our own design, so it carries the external-validity weight.

### 3.2 PALIMPSEST core (free)

SQLite-backed belief store. Each belief row carries the fields in the proposal; support, acceptance and justifications are append-only versioned by belief time (transaction time in bitemporal terms). Justifications form a JTMS-style dependency graph; an evidence item or belief losing support triggers propagation that re-evaluates every dependant and marks it "out" unless an independent justification remains. LLM-proposed implications enter as `flag_for_review` and never auto-accept. Admission applies the min(provenance, content) cap; support is combined across origin groups, not across documents. Revision versus update is chosen by the extractor's typed output (correction vs world-change), with the ambiguous case held as competing hypotheses.

The implementation goal is correctness and inspectability, not speed: a stream of 120 observations should replay in milliseconds, and every belief must be explainable as a path to evidence.

### 3.3 Baselines

Append-only log with query-time adjudication: the same extractor writes claims to a log; at query time the backbone receives the full log (or the top-k by recency and relevance when matching cost) and adjudicates. Its prompt gets the same care as PALIMPSEST's, including explicit instructions about retractions and recency, because a weak null proves nothing.

Rule-based bitemporal database: same claims, valid and belief time, supersession by recency and source priority, no justification graph.

Graphiti-style temporal graph: only if the open library runs on our backbone within ~$3; otherwise a minimal re-implementation or omission, reported either way.

Always-abstain and always-commit references (free): always-abstain answers every query as unresolved; always-commit takes the most recent observation at face value. Neither is a competitor; they bound the two failure modes. A real system must beat always-abstain on resolvable queries and beat always-commit on unresolved ones, otherwise uncertainty handling has become an escape from answering, or commitment an escape from reasoning.

### 3.4 Shared output contract (frozen before Phase 0; ratified 2 Oct 2026)

The claim: representation-neutral internally, with a shared output contract. Every system, including the always-abstain and always-commit references, answers through the same JSON object and receives the same mapping information and the same preserve-uncertainty instruction. Nothing below exposes gold labels, oracle environments, or hidden dependency rules.

**Canonical propositions.** A proposition is a tuple (entity, attribute, value, valid-interval?, context-condition?) over published vocabularies: a closed entity list per stream, a closed attribute list per domain, and per-attribute value types (closed vocabulary, or typed literal with a stated normalisation: ISO dates, integers, lower-cased strings). Yes/no queries are propositions with a polarity. Each query states its answer slot (which entity, attribute and time it asks about, and the permitted value type), so systems never have to guess the form of an acceptable answer. The mapping information handed to all systems is exactly: the vocabularies, the normalisation rules, and the observation IDs. In Setting 1 the declared dependency rules are also given, because that setting tests propagation with gold dependencies; in Settings 2–3 they are not.

**Observation IDs.** Every observation in a stream carries an ID visible to all systems, used for provenance.

**Status, operational definitions.** Each applies to the query's answer slot, and the four are mutually exclusive.

| Status | Meaning (relative to the benchmark's declared assumptions, never to independently verified world truth) | Example (Alex case) |
|---|---|---|
| `established` | The assertion holds under every admissible interpretation of the admitted observations. A refuted proposition is `established` with negative polarity. | "What locations have been reported for Alex?" → established: {London, Paris}, provenance o1, o2 |
| `possible` | A single asserted proposition holds under at least one but not all admissible interpretations. Used for yes/no slots and for single-proposition claims that the evidence permits but does not force. | "Did Alex move from London to Paris?" → possible: move(London→Paris) |
| `unresolved` | The slot asks for a value and the admissible interpretations yield different values; the system lists the alternatives and selects none. The distinction from `possible` is one proposition qualified versus a choice between propositions declined. | "Where does Alex live now?" → unresolved: alternatives {Paris, London, both} |
| `unknown` | No admitted observation bears on the slot, so there are no candidates at all. Distinct from `unresolved`, which has candidates. | "What is Alex's employer?" with no employer observations → unknown |

Gold status is derived from the ATMS oracle: one value across environments → `established`; several values → `unresolved` with exactly that alternative set; a yes/no proposition true in some environments but not all → `possible`; no bearing observation → `unknown`. The shared prompt contains these definitions and the four examples verbatim.

**Deterministic scoring.** Primary credit is exact: status must match gold, the assertion (or alternative set) must equal the gold proposition or set after normalisation, and a system that selects one unsupported interpretation on an `unresolved` or `possible` slot scores zero on that query. A lenient variant (superset of alternatives, or correct status with one extra alternative) is reported as a secondary metric and never enters H1–H4. No LLM judge is used on Settings 1–3; the free-text `explanation` field is optional, never scored, and used only for qualitative error analysis.

**Provenance validation.** A cited observation ID is *supporting* when it lies on an oracle justification path for the asserted proposition (for `unresolved`, for at least one listed alternative). Provenance precision (share of cited IDs that are supporting) and provenance recall (share of the oracle's minimal support set that is cited) are secondary metrics; merely existing IDs earn nothing.

**Malformed outputs and repair allowance.** Outputs are validated against the JSON schema and the vocabularies. Exactly one repair attempt is allowed per answer: the raw output is re-sent to the same backbone with a fixed, system-independent repair prompt, and its tokens are charged to that system's cost. A second failure is scored as `malformed`, which counts as wrong on every query (not as abstention), and the malformed rate is reported per system. The same allowance applies to extraction outputs during ingestion.

**Paraphrase fidelity and the extractor ambiguity diagnostic.** Extractor ambiguity is scored against the observable text, not generator intent, because a paraphrase can remove a temporal or exclusivity cue and make a sentence ambiguous that the generator meant to be unique. Before the evaluation set is frozen, every paraphrased observation passes a cue-recovery check: deterministic checks for cues that are string-detectable (dates, explicit correction markers), plus an independent cheap-model pass (GPT-5 nano, blind to the structured source, and not the extractor under test) that must recover the intended cue set. Observations failing either check are regenerated up to twice; those still failing are adjudicated by the author, and where the text is judged ambiguous the oracle is re-run with that cue removed so that the gold reflects the text as presented. Only then is the evaluation set frozen, with its queries and gold fixed for every system.

The extractor diagnostic reports, separately from ordinary slot errors (entity, attribute, value, time), *missed ambiguity* (frozen label ambiguous, extractor declares unique) and *spurious ambiguity* (frozen label unique, extractor declares ambiguous). An extractor's ambiguity declaration never changes which queries are answerable, never removes a query from the primary endpoint, and never alters gold.

**Cost accounting.** Schema, vocabulary and instruction tokens are charged to every system at full price in the accuracy–cost curves (no prompt-cache credit is assumed in the budget, although it will be used), as are repair attempts.

## 4. Experiments mapped to research questions

RQ1 (write-time vs query-time). Settings 1–3, all systems, three query-to-update ratios obtained by subsampling queries from the same streams (no extra ingestion cost). Output: accuracy–cost curves and the crossover cost, if any, with stream-level bootstrap CIs.

RQ2 (retraction under realistic dependencies). Setting 1 with gold dependencies and with controlled edge corruption (missing edges at 0/10/25/50%, spurious edges at 0/5/15%); Setting 2 with extracted dependencies, and extraction edge precision/recall measured against the structured source. Primary outcome, on *warranted* retractions only (those the oracle derives under every admissible interpretation): downstream error prevented after retraction, defined as the fraction of retraction-consequence queries answered in accordance with the oracle, minus the same fraction for the no-propagation ablation.

Ambiguity endpoints, reported separately and never pooled with the primary: premature commitment rate (the share of unresolved queries answered with status established, or with an assertion that holds under only some interpretations) and unsupported propagation rate (the share of dependent conclusions retracted or changed when the triggering retraction was not warranted). Both are reported next to resolvable-query accuracy and the always-abstain/always-commit references, so that a low commitment rate bought by refusing to answer is visible. In Setting 2 the extractor's own ambiguity detection (does it declare an observation as admitting several operators when the structured source says so, and only then) is measured as precision/recall against the generator, because an extractor that over-declares ambiguity would make a system look cautious for the wrong reason.

RQ3 (calibrated support). Claim-level Brier and ECE of PALIMPSEST support versus (a) calibrated source priors alone, (b) a logistic correctness predictor over evidence features trained on Setting 1 and tested on Settings 2–3 (free), (c) sampling-based answer confidence (k = 5, 1,000 queries). Held-out sources and domains are enforced by splitting source identities and entity domains between train and test streams. Risk–coverage curves replace abstention F1.

Secondary (poisoning). Attacker injects false observations at 1/5/20% through low-trust channels, then through one compromised trusted channel. Measured on Setting 1 (free) and on 20 natural-language streams. Reported as robustness under this attacker model only.

Ablations. All five from the proposal, run on replayed extraction logs so that only the verbalized-confidence ablation incurs new LLM calls.

Backbone robustness. 20% of Setting 2 rerun on Haiku 4.5 for PALIMPSEST and the log baseline; we report whether the sign of the RQ1 and RQ2 effects holds.

## 5. Pre-registered analysis plan

Primary hypothesis H1 (RQ2): in Setting 2 with extracted dependencies, on warranted-retraction consequence queries, PALIMPSEST's accuracy exceeds the append-only log's at matched cost by at least 10 percentage points (absolute), with the 95% stream-level bootstrap CI excluding zero. Unresolved queries are excluded from H1 by construction. Falsification follows the proposal: if the CI includes zero under extracted dependencies, unfamiliar sources (Setting 3) and matched cost together, we report the negative result and the crossover analysis as the main finding.

Secondary hypotheses: H2 (RQ1) the crossover cost exists and lies below a query-to-update ratio of 1.0; H3 (RQ3) PALIMPSEST support has lower ECE than verbalized confidence on held-out sources; H4 (ambiguity) PALIMPSEST's premature commitment rate on unresolved queries is lower than the log baseline's while its resolvable-query accuracy is not lower by more than 3 points (a joint criterion, so that abstention cannot buy H4). Secondary hypotheses use Holm correction over the family.

Units and uncertainty. The unit of analysis is the stream; paired differences per stream; 10,000-resample cluster bootstrap; effect sizes with CIs rather than p-values alone. Power: with 150 natural-language streams and an assumed SD of paired per-stream differences of 0.20, the half-width of a 95% CI is about 0.032, so a 10-point effect is detectable with large margin and a 5-point effect would still be resolved; Setting 3 with 30 streams has half-width ~0.07 and is reported as a transfer check, not a hypothesis test.

Everything in this section is frozen in `PREREGISTRATION.md` with a git tag before Setting 2 is run.

## 6. Budget

Prices are Batch API rates verified 2 Oct 2026; token counts are per-call estimates and the arithmetic is reproducible from `budget.py` in the repo.

| Item | Calls | In/Out tokens | Model | Cost |
|---|---|---|---|---|
| S2 paraphrase of 18,000 observations | 18,000 | 400 / 120 | GPT-5 nano | $0.61 |
| S2 extraction + dependency (shared) | 18,000 | 1,200 / 250 | GPT-5 mini | $7.20 |
| S2 answering: PALIMPSEST | 6,000 | 1,500 / 150 | GPT-5 mini | $2.02 |
| S2 answering: rule-based temporal DB | 6,000 | 1,200 / 150 | GPT-5 mini | $1.80 |
| S2 answering: append-only log (full log) | 6,000 | 8,500 / 300 | GPT-5 mini | $8.18 |
| S2 answering: Graphiti-style (optional) | 6,000 | 2,500 / 150 | GPT-5 mini | $2.77 |
| S2 ablation: verbalized confidence | 6,000 | 1,500 / 200 | GPT-5 mini | $2.33 |
| S3 extraction (3,000 obs) | 3,000 | 1,500 / 250 | GPT-5 mini | $1.31 |
| S3 answering: 3 systems | 3,600 | 4,000 / 200 | GPT-5 mini | $2.52 |
| STALE subsample ingest (100 scenarios, chunked) | 2,500 | 4,500 / 400 | GPT-5 mini | $2.41 |
| STALE subsample: log baseline, full context | 300 | 90,000 / 300 | GPT-5 mini | $3.46 |
| STALE subsample: PALIMPSEST answers | 300 | 2,000 / 300 | GPT-5 mini | $0.17 |
| LongMemEval KU subset (~80 items) | 2,560 | 3,500 / 300 | GPT-5 mini | $1.89 |
| RQ3 self-consistency, k=5 on 1,000 queries | 5,000 | 1,500 / 150 | GPT-5 mini | $1.69 |
| Poisoning: 20 NL streams × 2 systems | 1,600 | 3,000 / 200 | GPT-5 mini | $0.92 |
| Backbone check: 20% S2 extraction | 3,600 | 1,200 / 250 | Haiku 4.5 | $4.41 |
| Backbone check: 20% S2 answers × 2 systems | 2,400 | 5,000 / 200 | Haiku 4.5 | $7.20 |
| LLM judge for free-text answers (STALE/LongMemEval only) | 1,000 | 800 / 20 | GPT-5 nano | $0.02 |
| Contract: schema + vocabulary + instruction tokens on ~25k answers | 25,000 | 600 / 50 | GPT-5 mini | $3.12 |
| Contract: vocabulary/normalisation tokens on extraction prompts | 18,000 | 500 / 0 | GPT-5 mini | $1.12 |
| Contract: malformed-output repair, one attempt, ≤5% of answers | 1,250 | 1,000 / 200 | GPT-5 mini | $0.41 |
| Paraphrase fidelity: independent nano cue-recovery pass | 18,000 | 800 / 150 | GPT-5 nano | $0.90 |
| Paraphrase regeneration for flagged observations (≤15%) | 2,700 | 400 / 120 | GPT-5 nano | $0.09 |
| **Experiments subtotal** | | | | **$56.56** |
| Prompt/dev iteration reserve (nano, dev split) | | | | $10.00 |
| Contingency, 25% of experiments | | | | $14.14 |
| **Planned total** | | | | **$80.70** |
| Unallocated headroom | | | | $19.30 |

Contract tokens are counted at full price with no prompt-cache credit; actual spend will be lower. Spend gates: no Setting 2 run until Setting 1 results and the pre-registration are committed; no backbone-robustness run until the primary analysis is done; the Graphiti baseline is cut first if the extraction step overruns its estimate by more than 50%. A per-run cost logger records actual tokens so the paper reports measured, not estimated, costs.

## 7. Phases and gates (no deadline; ~10–12 weeks part-time)

Phase 0, week 1: freeze the claim language, contradiction relation, oracle semantics and the output contract of §3.4 (vocabularies, status definitions with examples, JSON schema, scorer, repair prompt); write `PREREGISTRATION.md` draft; re-check arXiv for concurrent work (STALE, Kumiho, Nous, TOKI, Graphiti) and record it in `RELATED.md`. Gate: the ATMS oracle produces identical environment sets and belief trajectories on two independent implementations of three hand-written streams, one of which is the Alex/London/Paris case with its four queries from §1.1.

Phase 1, weeks 2–3: generator and oracle; 500 structured streams; metric code with unit tests against hand-computed answers. Gate, three parts, all free: (a) a deliberately broken PALIMPSEST (propagation off) scores measurably worse on warranted-retraction consequence queries; (b) always-abstain scores well on unresolved queries and poorly on resolvable ones, and always-commit the reverse, confirming the two strata actually discriminate; (c) a PALIMPSEST variant forced to commit on every observation shows a measurable rise in unsupported propagation. If any part fails, the queries do not test the hypothesis and are redesigned before any money is spent.

Phase 2, weeks 3–5: PALIMPSEST core, rule-based DB baseline, log baseline; Setting 1 full results for RQ1–RQ2 and ablations (free). Gate: pre-registration tagged.

Phase 3, weeks 5–7: natural-language pipeline; dev split on nano; paraphrase cue-recovery check, regeneration, adjudication and evaluation-set freeze (git tag); Setting 2 full run; extraction fidelity and dependency edge P/R reported. Gate: budget spent ≤ $30.

Phase 4, weeks 7–8: Setting 3 construction and run; STALE and LongMemEval subsamples; RQ3 calibration; poisoning; backbone check.

Phase 5, weeks 9–11: analysis, figures, manuscript, reproducibility package (seeds, prompts, batch request files, cost logs), arXiv submission. An adversarial internal review pass is written as if by a hostile reviewer before submission.

## 8. Threats to validity, stated up front

Construct: the generator and the system share an author, so Settings 1–2 can be tuned to the method; Setting 3 and the external benchmarks are the only defence, which is why they are not optional. Internal: extraction prompts could be better tuned for PALIMPSEST's schema than for the log baseline; mitigated by a shared extractor and by giving the log baseline the same retraction-aware instructions. Statistical: 30 Setting 3 streams is small; reported as transfer evidence only. External: one backbone family at full scale; the Haiku check tests sign stability, not generality. Measurement: LLM-judged free-text answers on STALE/LongMemEval are a known bias source; judged with a different model family from the answerer, and a 100-item human spot-check by the author. Budget-induced: STALE is subsampled, so our STALE numbers are not comparable to the paper's headline figures and will be labelled as such.

## 9. Repository layout

`revise_stream/` (generator, oracle, perturbation menu), `palimpsest/` (store, justification graph, admission, revision), `baselines/`, `prompts/` (versioned, hashed into result files), `batch/` (request builders and response parsers for both providers), `eval/` (metrics, bootstrap, calibration), `analysis/` (notebooks producing every figure), `PREREGISTRATION.md`, `RELATED.md`, `budget.py`, `costs.jsonl`. Python 3.12, SQLite, numpy/pandas/scipy, no GPU dependencies. Every result file records the generator seed, prompt hash, model id and measured token counts.

## 10. Immediate next steps

Write the claim language, the per-claim-type resolution operator menus and the ATMS oracle semantics as a two-page note and have it criticised before code is written (the ambiguity rule itself is settled, §1.1); collect the Setting 3 raw sources (Wikipedia/Wikidata histories, correction notices) early because that is the slowest, least controllable part; set up the two Batch API accounts with hard spend limits of $60 (OpenAI) and $20 (Anthropic).
