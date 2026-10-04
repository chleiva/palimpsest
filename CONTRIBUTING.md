# Contributing

Thank you for considering a contribution. This is a research codebase with a pre-registered study behind it, so the main rule is: **nothing that changes a reported number may be merged silently.**

## Ground rules
1. **Semantics changes** (`revise_stream/oracle_v1.py`, `gold.py`, `timeline.py`, `model.py`) must come with (a) an update to `docs/SEMANTICS.md`, (b) a test in `tests/`, and (c) a run of `python scripts/oracle_validation.py` showing per-key vs global agreement. If a change alters any frozen gold file, say so in the PR and add a dated line to `docs/PREREGISTRATION.md` under *Deviations*; frozen results are never overwritten, they are superseded by a new version.
2. **Store changes** (`palimpsest/core.py`) must keep `scripts/systems_bench.py` and `scripts/rescore_structured.py` reporting zero disagreements with symbolic replay on status, assertion and alternatives.
3. **New baselines or systems** implement the output contract (`contract/answer.schema.json`) and are added to `nl/pipeline.py` / `scripts/run_setting1.py` so they are scored by the same code as everything else. No special-casing in the scorer.
4. **Paid runs** (anything using `nl/anthropic_client.py`) are not run in CI. If a PR needs one, open an issue first; include the ledger lines for any run you report.
5. **Numbers in the paper** come from `scripts/make_tables.py`; do not hand-edit `paper/tables/`.

## Workflow
```bash
pip install -r requirements.txt
python -m pytest tests -q            # must pass
python scripts/run_setting1.py data/setting1 --limit 50 --out /tmp/s1.json   # quick structured smoke test
```
Open a pull request with: what changed, why, which numbers (if any) move, and how you checked. Small, focused PRs are much easier to review than large ones.

## Good first issues
- A human-audit protocol and spreadsheet for extractions and adjudications (the study has none yet).
- A second backbone family through the same `LLMClient` interface (`nl/llm.py`).
- New perturbations for the generator (`revise_stream/generator.py`) with a hand-written reference stream in `revise_stream/streams/`.
- A STALE adapter under its native question interface.
- A per-key representation that avoids the 2^n enumeration on write.

## Conduct
Be kind and specific. Criticise claims and code, not people. Disagreements about semantics are expected; settle them with a stream file and a test.
