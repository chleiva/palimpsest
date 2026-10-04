# bridge/ — external data and (unused) LLM bridge

**What was actually used (3 Oct 2026).** All LLM calls in the paper go through
`nl/anthropic_client.py` (Anthropic Message Batches API, prompt caching, cost ledger in
`data/anthropic_ledger.jsonl`, hard cap). External data is downloaded by hand or by a
standard-library script and placed under `bridge/data/`:

- `bridge/data/longmemeval_oracle.json` — LongMemEval oracle file, downloaded by the author
  with `curl` from `huggingface.co/datasets/xiaowu0162/longmemeval-cleaned` (the "cleaned"
  release; the original repository path no longer serves the file). Used by
  `scripts/run_longmemeval.py`.
- `bridge/data/s3/`, `bridge/responses/s3_*.json` — Wikidata statement histories fetched by
  `python3 scripts/s3_fetch.py` (public CC0 data; about 75 requests; no AWS). Used by
  `scripts/build_setting3.py build`.

**`worker.py` is not needed** and was never run. It was written for an Amazon Bedrock path
that the execution environment could not use. It is safe by default: `bridge/config.json`
has `"bedrock_enabled": false`, under which no AWS client is created and `chat` /
`list_models` requests are refused; only the `fetch` op (public, allow-listed hosts) is
served. Enabling Bedrock means spending money with the logged-in AWS credentials; the
`list_models` op in particular probes every accessible model with a live call that the hard
cap does not cover. Do not enable it unless you want that.
