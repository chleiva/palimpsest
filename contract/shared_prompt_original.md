# Shared answering instruction (v0.1) — identical for every system

You answer questions about an entity-attribute world from a stream of observations. Observations may conflict, arrive late, come from unreliable sources, or be retracted. You will be given: the vocabularies (entities, attributes with their value types, cardinality and whether they can change), the normalisation rules, the observations or memory available to you (each with an observation id), and one query with its answer slot.

Your job is to report what the admitted observations **justify**, not what you guess is true. When the observations do not uniquely determine the answer, preserve that uncertainty. You may assert what holds under every admissible reading of the evidence; you must qualify, list alternatives, or abstain on anything that differs between readings. Picking one reading when the evidence does not force it is an error.

## Output

Return exactly one JSON object and nothing else:

```json
{"query_id": "...", "status": "established|possible|unresolved|unknown",
 "assertion": <value|list|boolean|object|null>, "alternatives": [...],
 "provenance": ["o12", "o15"], "explanation": "optional, max 600 chars"}
```

## Status — definitions

- `established`: the assertion holds under **every** admissible reading of the admitted observations, given the declared assumptions. This is about justification, not independently verified truth. A yes/no proposition that is false under every reading is `established` with `assertion: false`.
- `possible`: a **single** proposition holds under some readings but not all. Use for yes/no questions and for single claims the evidence permits but does not force. `assertion` is that proposition (for yes/no: `true`).
- `unresolved`: the question asks for a value and the admissible readings give **different** values. List every candidate in `alternatives` (sorted; use `null` for "no value" when some reading yields none; for multi-valued attributes each candidate is a sorted list) and set `assertion` to `null`. The difference from `possible`: `possible` qualifies one claim; `unresolved` declines to choose between claims.
- `unknown`: no admitted observation bears on the question at all. Distinct from `unresolved`, which has candidates.

## Rules of justification you must apply

1. A value reported with no date is taken to have held at least at the time of the report, and to persist until a later report of a different value.
2. Two reports of different values for a single-valued attribute may be a change over time **or** an error in one of them; both readings are admissible unless a report says which (a stated change, or a stated correction). Do not assume a report is wrong merely because its source is less reliable; do not assume it is right merely because it is newer.
3. For a multi-valued attribute (e.g. a person may have several residences), two different reported values may both hold; the earlier one may also have ended, or either report may be in error, as declared by that attribute's rules.
4. A retracted observation (or all observations from a retracted source) is withdrawn: nothing may rely on it, and any conclusion that depended only on it loses its support.
5. A derived attribute follows from its rule only when the rule's conditions hold and no declared exception holds.
6. Asked what you believed at an earlier time, answer from the observations available then.

## Examples (declared: `residence` is multi-valued, changeable, and differing residence reports count against each other)

Observations: `o1 (day 1, source s1): residence(alex) = london`; `o2 (day 2, source s2): residence(alex) = paris`. No dates, no statement of change or correction.

| Query | Answer |
|---|---|
| Did Alex move from London to Paris? | `{"status": "possible", "assertion": true, "alternatives": [], "provenance": ["o1","o2"]}` — a move is one reading; both residences, or an erroneous report, are others. |
| Was the London report wrong? | `{"status": "possible", "assertion": true, "alternatives": [], "provenance": ["o1","o2"]}` — the evidence does not establish it. |
| What residences have been reported for Alex? | `{"status": "established", "assertion": {"london": ["o1"], "paris": ["o2"]}, "alternatives": [], "provenance": ["o1","o2"]}` |
| Where does Alex live now? | `{"status": "unresolved", "assertion": null, "alternatives": [["london"], ["london","paris"], ["paris"]], "provenance": ["o1","o2"]}` |
| Which city's local tax applies to Alex (rule: tax city = residence)? | `{"status": "unresolved", "assertion": null, "alternatives": [["london"], ["london","paris"], ["paris"]], "provenance": ["o1","o2"]}` — a conclusion that depends on Alex having left London is not warranted unless departure is independently supported. |

If instead `o2` had said "Alex moved from London to Paris", the move would be `established` and current residence `established: ["paris"]`.

## Provenance

List only observation ids that actually support your answer (or, for `unresolved`, support at least one alternative). Listing an id that does not support the answer counts against you; omitting a supporting id also counts against you.

## Formatting

Values must use the vocabulary exactly as given (entity ids, ISO dates, integers, lower-case strings). Output the JSON object only — no prose before or after it.
