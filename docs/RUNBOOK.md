> **Superseded (3 Oct 2026).** The Bedrock bridge described below was never used: the Anthropic API was reachable from the workspace and every paid run went through `nl/anthropic_client.py` (see README.md). `bridge/worker.py` is now gated off (`bedrock_enabled: false`). External data: see `bridge/README.md` (`scripts/s3_fetch.py`, hand-downloaded LongMemEval file).

# Runbook — paid phases through the Bedrock bridge

All LLM calls go through `bridge/worker.py` running on the Mac host (the only machine with
AWS access). The research code runs in the cloud workspace (fast) and exchanges request /
response files with `bridge/requests` and `bridge/responses` in the shared `palimpsest`
folder. Every stage is resumable; a stage that needs a response that is not there yet
exits with code 3 and prints the request tag.

## 0. Start the worker (once, on the Mac)
Double-click `bridge/start_worker.command` (or `python3 bridge/worker.py` from the repo).
Hard cap: `bridge/config.json: hard_cap_usd` (default 60). Ledger: `bridge/ledger.jsonl`.

## 1. Model availability
(removed) a `list_models` request was queued at start; it would have probed every model with a live call — the response lists foundation
models, inference profiles and a 2-token probe per candidate ("ok" / error). Choose:
- CHEAP: cheapest probe-ok text model (expected `amazon.nova-lite-v1:0` or its `us.` profile)
- BACKBONE: primary backbone for extraction and adjudication (plan: Nova Lite primary for
  cost; stronger model, e.g. `amazon.nova-pro-v1:0` or Claude 3.5 Haiku, on a 20 % subset)

## 2. Setting 2 (150 streams)
```
python scripts/run_setting2.py data/setting2 data/s2 --bridge CHEAP BACKBONE --nonblocking
```
Repeat after shipping each pending request (`para_a0`, `cue_a0`, `para_a1`, `cue_a1`,
`para_a2`, `cue_a2`, `ext`, `adj`, `rep`) and bringing back its response. Expected spend
with Nova Lite everywhere: ≈ $6; with Nova Pro adjudication: ≈ +$25 (see budget.py).
Dev split first: `data/setting2_dev` → `data/s2_dev` (5 streams, ≈ $0.25) to check prompts.

## 3. Backbone robustness subset
`python scripts/run_setting2.py data/setting2 data/s2_strong --bridge CHEAP STRONG --limit 30 --nonblocking`
(reuses the frozen evaluation set? No — it re-extracts with the strong model; paraphrases
are shared by copying `data/s2/<sid>/para.json`, `flagged*.json`, `frozen.json` into `data/s2_strong/`.)

## 4. Matched-cost log variant
`--topk 40` restricts the log to the 40 most recent entries plus the queried key's entries.

## 5. Setting 3 (Wikidata)
`select` → ship `s3_select` → `plan` → ship `s3_revlists` → `revisions` → ship `s3_revcontent`
(≈1,600 fetches) → `build data/setting3` → run_setting2-style pipeline on `data/setting3`.

## 6. LongMemEval knowledge-update
`fetch` → ship → `prepare` → `extract` (ships `lme_extract`, `lme_map`) → `answer` (`lme_adj`) → `score` (`lme_judge`).

## 7. RQ3 (Setting 2 part): verbalised confidence and self-consistency
Add `--confidence` to run_setting2 (asks the adjudicator for a confidence field; runs k=5
samples at T=0.7 on 1,000 queries) — budget ≈ $2 with Nova Lite.

## 8. Tables and paper
`python scripts/make_tables.py && cd paper && latexmk -pdf main.tex`
