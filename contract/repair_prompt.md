# Repair instruction (v0.1) — identical for every system, used at most once per answer

The previous output did not validate against the required schema. Reproduce the **same answer** as a single valid JSON object with exactly these keys: `query_id` (string), `status` (one of `established`, `possible`, `unresolved`, `unknown`), `assertion` (value, sorted list, boolean, object, or null), `alternatives` (array, empty unless status is `unresolved`), `provenance` (array of observation id strings, no duplicates), and optionally `explanation` (string ≤ 600 characters). Do not change the substance of the answer. Output the JSON object only.

Validation error: {{error}}

Previous output:
{{raw}}
