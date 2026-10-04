# REVISE-Stream semantics v0.3 (Phase 0 freeze candidate)

Status: draft for criticism before code is trusted. Everything here is a *declared benchmark assumption*, not a claim about the world. The oracle sees only observations, declared source classes and declared domain semantics; it never sees the world trajectory.

## 1. Claim language

A **domain** declares a finite entity set `E`, an attribute table, and rules.

Each **attribute** `a` declares:

| Field | Values | Meaning |
|---|---|---|
| `type` | `entity`, `date`, `int`, `string`, `bool` | value type and normalisation (ISO dates, integers, lower-cased strings) |
| `cardinality` | `single`, `multi` | whether an entity can hold several values of `a` at one valid time |
| `changeable` | bool | whether the value can change over valid time (volatile vs stable) |
| `error_allowed` | bool | whether a report about `a` may be hypothesised erroneous when disputed |
| `derived` | bool | value is produced by rules, never observed directly |
| `competing_values` | bool | whether differing values on one key are evidence against each other (§5); default true |

A **proposition** is `(e, a, v)` with an optional **valid interval** and optional **context condition** `ctx` (a string; the key is `(e, a, ctx)`, `ctx` defaults to `""`). Propositions may carry **polarity** (`true`/`false`).

**Rules** are Horn clauses over propositions with variables, typed `strict` or `defeasible`; a defeasible rule carries an `exceptions` list of propositions whose truth at the query time blocks the rule. Rule heads are `derived` attributes. Example:

```
r1 (defeasible): work_city(?e, ?c) <- employer(?e, ?x), hq_city(?x, ?c)   exceptions: remote(?e, true)
```

The oracle applies only declared rules. LLM-proposed implications exist at the system level (typed `flag_for_review`), never in the oracle.

## 2. Time

Valid time `t` is an integer (days). Belief time is the index of observation arrival; each observation has a report time `t_rep`, non-decreasing in arrival order. The oracle at belief time `τ` uses exactly the observations with `t_rep ≤ τ`. "Now" for a query is its stated `t_now` (default: the belief time at which it is asked).

## 3. Observations and sources

Each **source** declares a reliability class in `{trusted, standard, low, blocked}` and an origin group (sources sharing an origin are correlated; grouping affects *support*, not admissibility).

An **observation** is one of:

* `assert(id, t_rep, source, e, a, v, polarity, valid_cue, op_cue)`;
* `retract(id, t_rep, source, target)` where `target` is an observation id or a source id (evidence withdrawal; a retracted observation is removed from the assumption set for all belief times ≥ `t_rep`).

`valid_cue` is one of `none`, `since t`, `at t`, `until t`, `interval [s, e)`. `op_cue` is one of `none`, `change` (the report states the world changed, optionally `from v_prev`), `correction` (the report states an earlier report was wrong, with `of id`).

**Anchor.** An observation's anchor time is the cue's start (`since`, `at`, `interval`) or, for `none`/`until`, its report time: *a report with no temporal cue is taken to assert that the value held at least at the time of reporting.* (Declared assumption A1.)

## 4. Admission (declared policy P0) and withdrawal

An observation is admitted iff its source class is not `blocked`. Reliability classes do not affect admissibility; they affect only the support layer (§8), which the oracle does not compute. This is the non-prioritised part: nothing below `blocked` is rejected, and nothing above it is privileged logically.

**A-SELF (withdrawal by self-correction).** A `correction` observation whose source shares the *origin* of the corrected observation's source withdraws the corrected observation, exactly as an explicit `retract` would, for all belief times ≥ its report time. This is a declared semantics about what an origin's later statement does to its own earlier statement (a newspaper correction notice, a registry amending its own entry), not an assumption about reliability. The corrected value asserted in the same notice is an ordinary report and may be disputed by other origins. A correction from a *different* origin withdraws nothing: it is a competing report with a correction cue (A-CORR, §6). Phase 0 applies A-SELF to the targeted observation only; whether an origin-wide withdrawal should also remove same-origin copies of the claim (mirrors) is an open point (§11).

Queries about an observation that is not admitted at `τ` (withdrawn, retracted, or not yet reported) have gold `unknown`.

**P1 (declared sensitivity variant, not the main configuration).** Under P1 the dispute relation of §5 is class-prioritised: `p` disputes `o` only if `rank(p) ≥ rank(o)` with `low < standard < trusted`, or `p` is corroborated by an admitted observation of the same key and value from a second origin. P1 is run only in Setting 1 as a pre-registered sensitivity analysis. It is not the main configuration because it builds a reliability ordering into the oracle that the systems under test are meant to estimate (RQ3), and because it would mark a trusted source's false statement `established` whenever only lower-ranked sources contradicted it.

## 5. Dispute and contradiction

Two admitted assertions `o, o'` on the same key `(e, a, ctx)` are **disputed** iff they have different values and the attribute declares `competing_values: true` (the default: a differing report is evidence against the other, as two residences are in the Alex case), or they have opposite polarity on the same value. An attribute may declare `competing_values: false` (e.g. nicknames), in which case differing values coexist and neither may be hypothesised erroneous on that ground. This is declared per attribute, never inferred. A **contradiction** (inconsistency under a joint truth labelling) arises only when both are labelled TRUE and:

* `a` is `single`-valued, not `changeable`, and values differ; or
* `a` is `single`-valued, `changeable`, values differ, and the declared valid intervals overlap (two `at`/`interval` cues overlapping; a `none`-cued report overlaps nothing before its anchor and is ended by the next different TRUE anchor, so it never contradicts by itself); or
* opposite polarities on the same value with overlapping intervals.

Dispute is the condition for *hypothesising error*; contradiction is the condition for *inconsistency*. The distinction is what makes "the London report may be wrong" admissible even when London-then-Paris is perfectly consistent as a change.

## 6. Interpretations (the ATMS environments)

Fix a belief time `τ` and the admitted, non-retracted assertions `O_τ`. An **interpretation** assigns:

* to every `o ∈ O_τ` a label `TRUE` or `ERR`;
* to every maximal run of TRUE assertions sharing a value on a `multi`-valued, `changeable` key (runs break where a different value's anchor intervenes), when a later run on the same key exists, a continuation label `CONT` or `ENDED`.

An interpretation is **admissible** iff all of the following hold:

* **A-ERR (error needs a dispute).** `o` may be `ERR` only if `error_allowed(a)` and `o` is disputed by some TRUE-labelled `o'`, or `o` is the target of a TRUE-labelled `correction` observation. Consequently every error label is explained by an accepted competing report; "everything is wrong" is never admissible.
* **A-CUE (cue resolution, policy P0c — main configuration, decided 2 Oct 2026).** A report carrying a `change` cue is *not* disputed by competitors anchored strictly earlier than itself: the cue identifies the revision operator (update), so the earlier value is explained rather than contested, and the operator ambiguity that A-ERR exists to preserve is absent. Competitors anchored at the same time or later still dispute it (a different value at the same time is not explained by a change). A `correction` cue does not shield (it asserts that another report erred, which is a reliability contest, resolved only by withdrawal: A-SELF or retraction). Variants: `P0` (literal: no cue shields; measured on 40 generated streams it leaves 2.3 warranted queries per stream and 48% unresolved slots, so the benchmark becomes abstention-dominated) and `P0cc` (correction cues shield too; a low-trust cross-origin "correction" would then establish its value over a trusted report). Both are available as declared variants.
* **A-CORR (correction cue).** A TRUE `correction` observation with `of = o_i` forces `label(o_i) = ERR`. The correction itself may be `ERR` only under A-ERR like any other report; if it is `ERR`, it forces nothing.
* **A-CHG (change cue).** A TRUE `change` observation with `from v_prev` presupposes the previous value: if any assertion of `v_prev` on that key is anchored *strictly before* it, at least one of them must be TRUE; on multi-valued keys the run of `v_prev` preceding the change is `ENDED`. The presupposition is about the value, not about a particular report: forcing a specific (latest) report TRUE would let an erroneous report of the old value make the stream inconsistent, and a report of `v_prev` anchored at the same time as the change is a competitor, not a presupposition. A `change` observation without `from` forces nothing beyond its own truth; on multi-valued keys it still leaves earlier values' continuation open.
* **A-CONS (consistency).** No contradiction (§5) among TRUE assertions.
* **A-STABLE.** On a non-`changeable` key all TRUE values are equal (this is A-CONS restated for the stable case).

The set of admissible interpretations at `τ` is `I_τ`. An interpretation is identified by its ERR set together with the timelines (§7) it induces for every key; two label assignments with the same ERR set and timelines are the same interpretation. (The ERR set must be kept because `erroneous(o)` queries distinguish label assignments with identical timelines.)

**Totality (relaxation ladder).** On generated streams every key has at least one admissible interpretation under P0c (verified on 500/500 streams), but extracted or adversarial streams, and the P1 variant, can make the conditions jointly unsatisfiable (e.g. a change presupposition whose only witness cannot be accepted under P1). The oracle is made total by a declared ladder applied per key only when the admissible set is empty: (1) drop A-CHG presuppositions; (2) additionally fall back to literal P0 dispute; (3) reject every report on the key (status `unknown`). Every application is counted and reported with the results.

**Minimality is deliberately not imposed.** A preference for fewer `ERR` labels would make "London→Paris was a move" established and "the London report was wrong" inadmissible, which is exactly the premature commitment the benchmark is designed to penalise. Preferences belong to the support layer, not to admissibility.

## 7. Timelines and answers under an interpretation

For each key and each TRUE assertion `o` with value `v` and anchor `s(o)`:

* its interval starts at `s(o)` (for `until t` cues: start unknown, treated as `-∞` — declared assumption A2: an `until` report without a start says nothing about when the value began);
* its interval ends at the explicit `until`/interval end if given; otherwise, on a `single` `changeable` key, at the next TRUE assertion with a different value on the same key — the change point is unknown and lies in the half-open gap `(s(o), s(o_next)]`; on a `multi` key, at `+∞` if `CONT`, or in the gap before the next different TRUE anchor if `ENDED`; on a non-`changeable` key, at `+∞`;
* a TRUE negative-polarity assertion on `(e, a, v)` ends `v`'s interval at its anchor (declared assumption A3) and contradicts any TRUE positive assertion on `v` anchored later.

**Persistence (A4, law of inertia).** Absent a later TRUE assertion with a different value, a value persists to `+∞`. This is a benchmark assumption about justified belief, not about truth.

**Value at time t under interpretation i.** `val_i(e, a, ctx, t)` is the set of values whose interval covers `t`. If `t` lies inside an unknown-change-point gap between `v_prev` and `v_next`, the result is the set `{v_prev, v_next}` for that interpretation (intra-interpretation uncertainty). Derived attributes are computed by forward-chaining the declared rules on `val_i(·, t)`; a defeasible rule whose exception holds at `t` under `i` contributes nothing; variables ranging over sets produce the union of candidates.

## 8. Support (not part of the oracle)

Support is the system's probability that a claim is true for its interval; it is estimated by PALIMPSEST from source class, origin grouping, recency by volatility, and the min(provenance, content) cap, and it is evaluated for calibration against the *world* trajectory (RQ3), not against the oracle. The oracle defines only what is justified, not how likely.

## 9. Queries and gold

Query slots: `current(e,a,ctx,t_now)`, `asof(e,a,ctx,t)`, `belief_asof(e,a,ctx,τ')` (what was justified at belief time `τ'` about "current" then), `yesno(prop)` with `prop ∈ {holds(e,a,v,t), changed(e,a,v1→v2), erroneous(o)}`, `reported(e,a,ctx)` (observational: all admitted non-retracted reported values with provenance), and `downstream(e,a_derived,t)`.

Gold is computed from `I_τ`:

* value slots: `cands = ⋃_i val_i(·)` (each interpretation may contribute several candidates via gaps; the empty set contributes the candidate `∅`). One candidate → `established` with that value; several → `unresolved` with exactly that set; no interpretation and no candidates → `unknown`. For `multi` keys a candidate is a *set* of values, and alternatives are sets.
* yes/no slots: true in every `i` → `established` (positive); false in every `i` → `established` (negative); mixed → `possible`.
* `reported`: always `established`, value = the set of reported values with observation ids.

**Warranted-retraction consequence queries.** A `downstream` query asked at `τ ≥ t_rep(retract)` is tagged `warranted` iff its gold status at `τ` is `established` and differs (status or value) from its gold at `τ − 1`. Only `warranted` queries enter the primary endpoint H1; the others on the same template enter the ambiguity endpoints.

## 10. Worked case (Alex)

Domain: `residence` is `entity`, `multi`, `changeable`, `error_allowed`. Observations: `o1 (t=1, s1): residence(alex)=london`, `o2 (t=2, s2): residence(alex)=paris`, both `valid_cue=none`, `op_cue=none`. At `τ=2`:

| Labels | Admissible? | Current residence |
|---|---|---|
| o1 TRUE, o2 TRUE, o1 CONT | yes | {london, paris} |
| o1 TRUE, o2 TRUE, o1 ENDED | yes ("move") | {paris} |
| o1 ERR, o2 TRUE | yes (o1 disputed by TRUE o2) | {paris} |
| o1 TRUE, o2 ERR | yes | {london} |
| o1 ERR, o2 ERR | no (A-ERR: no TRUE competitor explains either error) | — |

Gold: `current(alex, residence)` → `unresolved`, alternatives `{{london,paris}, {paris}, {london}}`. `yesno changed(alex, residence, london→paris)` → `possible` (true only in the ENDED row). `yesno erroneous(o1)` → `possible`. `reported(alex, residence)` → `established` `{london: [o1], paris: [o2]}`. `downstream` on anything that depends on "alex left london" → not `warranted`.

If the domain instead declared `residence` as `single`-valued, the CONT row disappears and the alternatives become `{{paris}, {london}}`; the yes/no answers are unchanged. Cardinality is declared, never inferred.

## 11. Open points for criticism before freeze

1. **Decided 2 Oct 2026: P0 with A-SELF is the main configuration; P1 is a declared Setting 1 sensitivity variant.** Under P0, `established` means *undisputed among admitted observations*: any competing report from any non-blocked source, including a `low` one, makes the slot `unresolved`, and a correction never resolves a dispute by itself because the correction may be the erroneous report (birthdate stream, τ=4 and τ=7). Reliability never resolves disputes at the oracle level; only evidence retraction does, and the support layer carries the graded judgement. This is the literal reading of the frozen rule ("source priors alone should not silently supply" a resolution). The alternative, policy **P1**, would declare a reliability order in which a `trusted` report is not disputed by a `low` one unless corroborated by a second origin — a form of class-prioritised admissibility that must be declared explicitly if adopted. Both oracles implement P0c (default), literal P0, P0cc and P1 (`policy=`); the birthdate stream exercises A-SELF (citizenship) and the P0/P1 difference (tests/test_gate_phase0.py).
6. A-SELF withdraws only the targeted observation. An origin-wide variant (withdraw every same-origin observation with the same key and value, e.g. mirrors of a corrected page) is plausible and should be decided in Phase 1 when the generator's correlated-source model is written.
2. Interpretation identity (§6) is (ERR set, timelines); both oracles implement it and the Phase 0 gate compares these sets directly, plus all gold answers. Gate result on 2 Oct 2026: identical on all three streams at every belief time (tests/test_gate_phase0.py).
3. Gaps (§7) create intra-interpretation candidate sets; `asof` queries inside gaps are therefore `unresolved` by construction. This is intended (unknown change dates are a listed perturbation), but it means such queries must be stratified as unresolved and excluded from H1.
4. Negative-polarity assertions (A3) are included for completeness; Phase 1 streams may omit them.
5. `belief_asof` returns the status the oracle would have given at `τ'`; a system answering it must reproduce its own earlier state, which is where bitemporal versioning is tested. The log baseline can do this by filtering the log by report time, so the test is fair.
