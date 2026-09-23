# Submission: TwoSourceClaimResolver

**Category:** Intelligent Contracts
**Type:** standalone reusable primitive
**Language:** Python / GenVM
**Source:** `contracts/TwoSourceClaimResolver.py`

## Purpose

Give other builders a drop-in contract that turns a natural-language world claim plus two public URLs into an on-chain verdict (`TRUE` / `FALSE` / `UNRESOLVED`) that independent GenLayer validators can re-derive.

The primitive is meant to sit under:

- event-settled markets and parametric perps
- agent-to-agent escrow that should pay only when a public fact is true
- any app that today would otherwise trust one API or one model

It is not a frontend and not a sports-market fork. The claim text and both sources are chosen by the caller. The interesting part is the consensus rule, not a particular sport or website.

## How consensus is used

Resolution is the only non-deterministic write.

1. Deterministic preamble copies the frozen claim into memory and rejects calls that are too early, already resolved, or unknown.
2. `leader_fn` fetches URL A and URL B with `gl.nondet.web.get`, then calls `gl.nondet.exec_prompt(..., response_format="json")` to extract a structured object.
3. `validator_fn` checks that the leader returned `gl.vm.Return`, re-runs the same fetch + extract path, and accepts only when `_results_equivalent` returns true.
4. Deterministic epilogue writes the accepted verdict and pays or refunds escrow. Transfers never happen inside the non-deterministic block.

Equivalence is **comparative and field-selective**:

- compared: `verdict`, `source_a_status`, `source_b_status`
- ignored: `reasoning`, quotes
- forced `UNRESOLVED`: failed fetch, source contradiction, `TRUE` without quotes

`strict_eq` would flake on live pages and LLM wording. A format-only validator would accept a leader that invented a `TRUE`. Comparative re-derivation plus hard gates is the point of the submission.

## State

`TreeMap[str, Claim]` keyed by sequential string IDs. `Claim` is an `@allow_storage` dataclass. Terms (`claim_text`, both URLs, beneficiary, earliest time, escrow) are immutable after `open_claim`. Only `status`, `verdict`, audit strings, `resolved_by`, and `escrow_wei` change later.

## Settlement policy

| Verdict | Escrow |
|---|---|
| `TRUE` | paid to beneficiary |
| `FALSE` | refunded to creator |
| `UNRESOLVED` | refunded to creator |
| cancel while `OPEN` | refunded to creator |

`UNRESOLVED` is a first-class outcome. Paying on thin evidence is worse than refunding.

## Tests and documentation

- `README.md` — purpose, consensus diagram, API, what this is not
- `tests/test_equivalence.py` — 12 unit tests of the decision rule and extractor overrides, runnable with CPython (`python tests/test_equivalence.py`)

Studio / gltest integration tests need a live or mocked GenVM. The unit file is included so reviewers can inspect the equivalence rule without that environment.

## Reuse notes for other builders

Fork the file, keep `open_claim` / `resolve_claim`, and change only:

- the extractor prompt (domain language)
- the number of sources (extend `_leader_resolve`)
- the settlement policy (e.g. hold `UNRESOLVED` escrow instead of refunding)

Do not weaken `_results_equivalent` into a schema check. If the validator does not re-fetch, the contract stops being an Intelligent Contract and becomes a leader-trusting wrapper.
