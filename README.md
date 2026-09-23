# TwoSourceClaimResolver

Standalone GenLayer Intelligent Contract primitive that settles a **binary real-world claim** from **two independent public sources**, then optionally pays escrow.

This is not an LLM wrapper and not a one-off demo. Other builders can reuse it as:

- a prediction / event resolver (did the named event happen?)
- a parametric trigger (commodity disruption, regulatory filing, outage)
- a lightweight adjudication layer in front of an agent escrow

## Why this belongs on GenLayer

A normal smart contract cannot read two news pages and decide whether they support a sentence like:

> “OPEC+ agreed a 500,000 bpd output cut at the 12 September 2026 meeting.”

A single-operator oracle can, but one party always wants the opposite answer. That is the adversarial structure GenLayer is for:

| False verdict | Who benefits |
|---|---|
| False `TRUE` | Beneficiary receives escrow; anyone long the claim |
| False `FALSE` | Creator keeps escrow; anyone short the claim |
| False `UNRESOLVED` | Nobody is paid; the market stays open. Preferred to a wrong binary. |

If nobody benefits from a wrong answer, multi-validator consensus is theater. Here they do.

## How consensus is used

`resolve_claim` is the only method that enters a non-deterministic block.

```
creator locks claim text + URL A + URL B + earliest time + optional escrow
        |
        v
anyone calls resolve_claim after earliest_resolve_unix
        |
        v
leader fetches both pages (gl.nondet.web.get)
leader asks an LLM for a structured verdict (gl.nondet.exec_prompt, JSON)
        |
        v
each validator independently re-fetches both pages and re-runs the extractor
        |
        v
validator accepts the leader iff decision fields match
        |
        v
deterministic code writes verdict and settles escrow
```

### Equivalence rule (decision fields only)

Validators **re-derive** the result. They do not rubber-stamp the leader.

Must match exactly:

- `verdict` ∈ `{TRUE, FALSE, UNRESOLVED}`
- `source_a_status` ∈ `{ok, fail}`
- `source_b_status` ∈ `{ok, fail}`

Explicitly **not** compared:

- `reasoning` (model wording)
- `quote_a` / `quote_b` (phrasing)

Hard gates applied in both the extractor and the validator:

1. If either source fails to load, verdict is forced to `UNRESOLVED`.
2. `TRUE` requires both sources `ok` and a quote from each page.
3. Contradictory sources cannot finalize as `TRUE` or `FALSE`.
4. Escrow pays the beneficiary only on `TRUE`. `FALSE` and `UNRESOLVED` refund the creator.

This is a custom `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` validator, not `strict_eq` and not a format-only check.

Storage is copied with `gl.storage.copy_to_memory` before the non-deterministic block. Web/LLM work never reads contract storage directly. Settlement (`emit_transfer`) happens only after consensus returns.

## State design

```
Claim
  id, creator, beneficiary
  claim_text                  # frozen at open_claim
  source_a_url, source_b_url  # frozen at open_claim
  earliest_resolve_unix
  escrow_wei
  status                      # OPEN | RESOLVED | CANCELLED
  verdict                     # UNSET | TRUE | FALSE | UNRESOLVED
  reasoning, quote_a, quote_b # audit trail, not consensus keys
  resolved_by
```

Lookups are `TreeMap[str, Claim]`. IDs are also appended to `DynArray[str]` so callers can list them. Views return canonical JSON (`sort_keys=True`) so other contracts and frontends can parse them.

## Public API

| Method | Kind | What it does |
|---|---|---|
| `open_claim(claim_text, source_a_url, source_b_url, beneficiary, earliest_resolve_unix)` | payable write | Locks terms + any attached GEN |
| `cancel_claim(claim_id)` | write | Creator refund while still `OPEN` |
| `resolve_claim(claim_id)` | write | Fetches sources, reaches consensus, settles |
| `get_claim(claim_id)` | view | JSON snapshot |
| `list_claim_ids()` | view | JSON array of IDs |
| `get_next_id()` | view | Next sequential ID |

## What this is not

- Not a hello-world / storage example
- Not “ask an LLM whether X is true” with no evidence
- Not a format-only validator (`isinstance(dict)` is necessary but never sufficient)
- Not a full product with a frontend (submit that under Projects)
- Not a sports prediction-market fork: sources are caller-chosen, the verdict set includes `UNRESOLVED`, and escrow settlement is first-class

## Suggested first claim (manual Studio test)

```
claim_text:
  The official example.com page is reserved for use in documentation
  and examples and is administered by IANA.

source_a_url: https://example.com
source_b_url: https://www.iana.org/domains/reserved
earliest_resolve_unix: 0
beneficiary: <your address>
```

Expected path: both pages load, both mention IANA / example.com reservation, verdict `TRUE` (or `UNRESOLVED` if a validator cannot retrieve one of the pages — that is correct behavior, not a bug).

## File map

```
contracts/TwoSourceClaimResolver.py   # the primitive
tests/test_equivalence.py             # pure-Python tests of the decision rule
SUBMISSION.md                         # reviewer-facing writeup
```

Deploy the single file in `contracts/` through GenLayer Studio or:

```
genlayer deploy --contract contracts/TwoSourceClaimResolver.py
```
