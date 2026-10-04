# Zenodo record — field by field (DOI 10.5281/zenodo.23127764)

## Files (upload both)
- `PALIMPSEST_v1.0.pdf` — in ~/palimpsest (34 pages; DOI and licence printed on page 1)
- `palimpsest-v1.0.zip` — in ~/palimpsest (37,393,652 bytes; SHA-256 4c0fc8106b00a54c2f5990df72e90af006671611ca0a53f8a06609e5d961cdb6; 8,944 files; manifest inside)

## Basic information
- Digital Object Identifier: 10.5281/zenodo.23127764 (already reserved — leave as is)
- Resource type: Publication → Working paper
- Title: PALIMPSEST: Evaluating Retraction and Uncertainty in LLM Memory
- Publication date: 2026-10-03
- Authors/Creators: Leiva Beltran, Christian — affiliation: Independent researcher (or your organisation) — ORCID if you have one
- Description: see below (paste as is; Zenodo accepts basic HTML/plain text)
- Licenses: Creative Commons Attribution 4.0 International (matches page 1 of the PDF and LICENSE in the zip)
- Copyright: © 2026 Christian Leiva Beltran

## Recommended information
- Contributors: (leave empty; AI assistance is disclosed in the paper's author note, not as a contributor)
- Keywords and subjects: belief revision; truth maintenance; LLM memory; agent memory; retraction; evidence withdrawal; justified belief; benchmark; calibration; bitemporal; knowledge conflicts; pre-registered study
- Languages: English (eng)
- Dates: (leave empty)
- Version: 1.0
- Publisher: Zenodo (default)
- Funding: (none)
- Alternate identifiers: (none)
- Related works:
  - arXiv:2607.23929 — "Is referenced by"? No: use relation **"References"** (MemTX)
  - arXiv:2605.06527 — References (STALE / CUPMem)
  - arXiv:2608.19652 — References (StateMemBench)
  - arXiv:2610.00094 — References (Nous)
  - https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned — relation "Is derived from" (LongMemEval data used, not redistributed)
  - https://www.wikidata.org — relation "Is derived from" (Setting 3 revision histories, CC0)
- References: (optional; the PDF bibliography covers it)

## Software (fill only if you create a GitHub repository; otherwise leave empty)
- Repository URL: (none yet)
- Programming language: Python
- Development Status: Active

## Publishing information
- Journal / Imprint / Thesis / Conference: leave empty (not published elsewhere)

## Visibility
- Public (record and files). No embargo.

## Description (paste into the Description field)

Working paper, not peer reviewed. Version 1.0, 3 October 2026.

LLM memories built as retrieval over an append-only store fail when the evidence itself changes: a report is withdrawn, an earlier statement corrected, a change reported late. This study examines propagating the retraction of evidence through the justifications of the conclusions that depended on it, while refusing to commit to a revision the evidence does not determine. It gives a declared semantics of justified belief for observation streams (an assumption-based truth-maintenance oracle with operator cues, dispute, correction and withdrawal, validated against a brute-force global enumeration), a benchmark generator, REVISE-STREAM, that keeps the world, the observations and what they justify separable, and an output contract that scores uncertainty handling for every system alike. PALIMPSEST, an incremental store whose derived beliefs pin the evidence versions that justified them, returns the same status, value and alternatives as symbolic replay on every benchmark query at six to twelve times lower measured latency; it saves total work only when queries are at least as frequent as observations, and its write cost grows exponentially in reports per key. Retraction propagation, not ordinary updating, prevents downstream errors (about 20 points in every setting, including streams derived from Wikidata revision histories). Symbolic maintenance beats a prompted LLM adjudicator over the same extracted claims by 44.2 points (original protocol, 100 streams; 59.0 under an amended contract on 30) while committing on a seventh as many unresolved slots, but a rule-based adjudicator matches it. A regime analysis shows that refusing to assume recency pays only where the latest report is wrong; a pre-registered self-update rule closes the single-source case at a small measured cost. One pre-registered hypothesis fails and one could not be executed as registered; every deviation is dated.

The deposit package (palimpsest-v1.0.zip, SHA-256 686cf0bb…77dc6) contains the code (semantics and both oracles, generator, store, baselines, scoring, natural-language pipeline), the frozen evaluation sets with gold and hidden labels, every prompt (original and amended output contract), every raw model output and batch record, the cost ledger (total measured spend $88.85), the pre-registration with its dated deviations and outcomes, the Wikidata revision contents used for Setting 3 (CC0), and the scripts that regenerate every table and figure from cached outputs without an API call (README_DEPOSIT.md). The LongMemEval dataset is not redistributed; it is identified by its source release. Research design, semantics, code and experiments were developed with AI assistance (Claude); the author directed the work, reviewed every result and takes responsibility for the content.

Model identifiers: claude-haiku-4-5-20251001 (all stages) and claude-sonnet-4-6 (15-stream sign-stability subset), Anthropic Message Batches API, 3 October 2026.
