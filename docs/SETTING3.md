# Setting 3 — streams assembled from Wikidata statement histories (3 Oct 2026)

Setting 3 is the transfer setting: streams that nobody on the project designed, assembled from
public CC0 revision histories with no LLM in the loop for construction. It is reported as
descriptive transfer evidence (pre-registration: "reported, not tested"). This note records every
design decision of the assembler, in the order they were made, so that a reader can judge how much
of the result is the data and how much is the mapping.

## Data

- `scripts/s3_fetch.py` (standard library only; run by the author on his machine; ~250 requests,
  0.5 s apart, descriptive User-Agent). Stage 1: a SPARQL query selects humans (P31=Q5) with at
  least three employer (P108) statements of which at least one has an end date (P582) and at least
  one statement on a tracked property (P108, P551, P39, P27, P569) with deprecated rank; `LIMIT 60`,
  40 kept after a seeded shuffle. Stage 2: up to 40 revisions per entity sampled evenly across its
  history (revision ids via `prop=revisions`, contents 50 per request). Stage 3 (`orgs`): the same
  for the 128 organisations that appear as employer values (15 revisions each), so that the derived
  chain exists. Fetched 3 Oct 2026: 1,564 person revisions, 1,910 organisation revisions.
- `scripts/build_setting3.py build` diffs consecutive sampled revisions. The sampling means
  intermediate edits between two sampled revisions collapse into one diff; this under-counts
  short-lived statements and is a conservative choice (fewer events, not spurious ones).

## Mapping (observation construction)

| Wikidata event between two sampled revisions | Observation |
|---|---|
| claim added (not deprecated) | `assert`; `valid: since <P580 start>` when the claim has a start qualifier |
| claim's value edited in place | `assert` with `op_cue: correction` of the previous observation |
| claim rank set to deprecated | `retract` of that observation, source `wd_editors` |
| claim removed | `retract` of that observation, source `wd_editors` |

Belief time = day index of the revision. Day 1 = the earliest date in the stream: the first
sampled revision, or the earliest start qualifier if that lies before it (valid time may precede
belief time; this keeps the order of `since` cues). Year- and month-precision dates map to the
first day of the period; year-precision birth dates are kept as `YYYY`.

Sources (visible to systems as class + origin only, as in Settings 1–2): a reference with
`P248 stated in` → origin = that item, class `trusted` if the item's label hints at an authority
(registry, library, gazette, …; `AUTHORITY_HINTS`), else `standard`; a reference URL → origin =
domain, `standard`; no reference → origin `wd_unreferenced`, `low`; editorial deprecation/removal
→ `wd_editors`, `standard`. In the fetched data 331 of 417 assertions are unreferenced (`low`),
86 are `standard`; no reference qualified as `trusted`.

Per-key assertions are capped at 7 (earliest kept) for the oracle's enumeration bound; dangling
correction/retraction references to dropped observations are removed. Streams with fewer than 8
observations are dropped (40 → 30).

## Schema decisions (the ones that matter)

1. **`employer` is a multi-valued, non-changeable affiliation set** (`competing_values: false`).
   Wikidata's P108 lists every employer over a career, usually without start dates; most people in
   the selection have 3–7 affiliations recorded by unreferenced statements. Under the declared
   semantics a single-valued changeable key with several undated values is a dispute (unresolved),
   and a multi-valued changeable key leaves every earlier value's continuation open (SEMANTICS §5,
   the Alex residence example), so both readings make the derived slot unresolved almost everywhere
   (first builds: 51 of 85 downstream queries unresolved, 1 warranted). The affiliation-set reading
   matches what the property records; retraction and correction still remove or replace members of
   the set. Consequence: the derived slot `work_city` is the **set of headquarters cities of the
   person's recorded affiliations**, and a warranted downstream query is one where a deprecation,
   removal or correction of an employer statement (or a change of an organisation's headquarters)
   changes that set. This is the retraction-propagation question in its Wikidata form.
2. `residence`, `citizenship` multi-valued (citizenship non-changeable, no competing values);
   `position`, `hq_city`, `ceo` single-valued changeable; `birth_date` single non-changeable.
3. Rules as in Settings 1–2: `work_city(e) <- employer(e, x), hq_city(x, c)` (defeasible),
   `ceo_city(o) <- ceo(o, p), work_city(p, c)`.

## Surface rendering

Entity ids are pseudonymised with the same fictional name pools as Settings 1–2 (people,
organisations, cities; new pools for countries and positions); source keys get pseudonymous outlet
names ("an unreferenced OpenPedia entry", "Catalogue 3", "Website 2", "the OpenPedia editors").
Dates are the real revision dates. Rationale: the paper scores justified belief given the
observations, so a backbone must not be able to answer from parametric knowledge of the real
person; the *structure* (timing, conflicts, deprecations, corrections) is real, the surface is not.

## Resulting set (30 streams)

497 observations (417 asserts, 80 retractions; 30 corrections, 91 `since` cues); 714 queries after
the declared selection (every generated query is kept because fewer than 44 exist per stream);
gold: 515 established, 165 unknown, 28 unresolved, 6 possible; 72 warranted direct and 24
warranted downstream queries (0.8 per stream; 13 of 30 streams have at least one). The downstream
stratum is thin: the transfer result is reported with its CI and the count, not as a test.

## What this does not establish

The selection query asked for histories with deprecated statements and ended employments, so the
30 streams are enriched for exactly the phenomena the paper studies; they are not a random sample
of Wikidata. The mapping of "deprecated rank" to withdrawal is ours. No human checked the 30 streams
against the live Wikidata pages.
