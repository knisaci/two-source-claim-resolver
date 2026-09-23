# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
TwoSourceClaimResolver
======================
Reusable Intelligent Contract primitive for settling a binary real-world claim
from two independent public sources.

A claimant locks terms they cannot later edit: the claim text, two source URLs,
and (optionally) an escrow that pays a beneficiary only if the network agrees
the claim is TRUE. Anyone may trigger resolution after `earliest_resolve_unix`.

Consensus is structural, not decorative:
- Leader and each validator independently fetch both source pages.
- An LLM extracts a structured verdict from that live evidence.
- Validators accept the leader only when the *decision fields* match.
- TRUE/FALSE never finalize if either source is unreachable or the two
  sources contradict each other.

Who benefits from a false TRUE: the beneficiary (escrow) or anyone long the
claim. Who benefits from a false FALSE: the depositor (keeps escrow) or
anyone short the claim. That adversarial structure is why this belongs
on GenLayer rather than a single-operator oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from genlayer import *
import json


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


def _pay(to: Address, amount: u256) -> None:
    if int(amount) <= 0:
        return
    _Recipient(to).emit_transfer(value=amount)


VERDICT_UNSET = "UNSET"
VERDICT_TRUE = "TRUE"
VERDICT_FALSE = "FALSE"
VERDICT_UNRESOLVED = "UNRESOLVED"

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"
STATUS_CANCELLED = "CANCELLED"

SOURCE_OK = "ok"
SOURCE_FAIL = "fail"

_MAX_PAGE_CHARS = 8000
_MIN_CLAIM_LEN = 12
_MIN_URL_LEN = 12


@allow_storage
@dataclass
class Claim:
    id: str
    creator: Address
    beneficiary: Address
    claim_text: str
    source_a_url: str
    source_b_url: str
    earliest_resolve_unix: u256
    escrow_wei: u256
    status: str
    verdict: str
    reasoning: str
    quote_a: str
    quote_b: str
    resolved_by: Address


def _is_http_url(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith("https://") or u.startswith("http://")


def _truncate(text: str, limit: int = _MAX_PAGE_CHARS) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def _safe_decode(body) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(body)


def _normalize_verdict(raw) -> str:
    if raw is None:
        return VERDICT_UNRESOLVED
    v = str(raw).strip().upper()
    if v in (VERDICT_TRUE, VERDICT_FALSE, VERDICT_UNRESOLVED):
        return v
    return VERDICT_UNRESOLVED


def _normalize_source_status(raw) -> str:
    s = str(raw).strip().lower() if raw is not None else SOURCE_FAIL
    return SOURCE_OK if s == SOURCE_OK else SOURCE_FAIL


def _fetch_source(url: str) -> dict:
    try:
        resp = gl.nondet.web.get(url)
        status = int(getattr(resp, "status_code", 0) or 0)
        body = _truncate(_safe_decode(getattr(resp, "body", b"")))
        ok = 200 <= status < 400 and len(body.strip()) > 0
        return {
            "url": url,
            "http_status": status,
            "status": SOURCE_OK if ok else SOURCE_FAIL,
            "text": body if ok else "",
        }
    except Exception as exc:
        return {
            "url": url,
            "http_status": 0,
            "status": SOURCE_FAIL,
            "text": "",
            "error": str(exc)[:200],
        }


def _extract_verdict(claim_text: str, source_a: dict, source_b: dict) -> dict:
    prompt = f"""You are an evidence adjudicator. Decide whether the CLAIM is supported
by the two independently fetched source pages.

Rules:
- TRUE only if BOTH sources are reachable and BOTH support the claim with
  concrete, on-page evidence. Support means the page states facts that make
  the claim true, not merely related commentary.
- FALSE only if BOTH sources are reachable and at least one source
  directly contradicts the claim, and neither source affirms it.
- UNRESOLVED in every other case: a source failed to load, the pages are
  off-topic, the event has not happened yet, the sources contradict each
  other, or the evidence is only rumor/opinion.

CLAIM:
{claim_text}

SOURCE A URL: {source_a.get("url")}
SOURCE A FETCH STATUS: {source_a.get("status")} HTTP {source_a.get("http_status")}
SOURCE A TEXT:
{source_a.get("text") or "(empty or failed)"}

SOURCE B URL: {source_b.get("url")}
SOURCE B FETCH STATUS: {source_b.get("status")} HTTP {source_b.get("http_status")}
SOURCE B TEXT:
{source_b.get("text") or "(empty or failed)"}

Return JSON only with this exact schema:
{{
  "verdict": "TRUE" | "FALSE" | "UNRESOLVED",
  "source_a_status": "ok" | "fail",
  "source_b_status": "ok" | "fail",
  "sources_agree": true | false,
  "quote_a": "short quote from source A or empty string",
  "quote_b": "short quote from source B or empty string",
  "reasoning": "one or two sentences"
}}
"""
    raw = gl.nondet.exec_prompt(prompt, response_format="json")
    if isinstance(raw, str):
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
    elif isinstance(raw, dict):
        data = raw
    else:
        raise gl.vm.UserError("LLM returned unusable payload")

    verdict = _normalize_verdict(data.get("verdict"))
    sa = _normalize_source_status(data.get("source_a_status"))
    sb = _normalize_source_status(data.get("source_b_status"))
    if source_a.get("status") != SOURCE_OK or source_b.get("status") != SOURCE_OK:
        sa = source_a.get("status", SOURCE_FAIL)
        sb = source_b.get("status", SOURCE_FAIL)
        verdict = VERDICT_UNRESOLVED
    if sa != SOURCE_OK or sb != SOURCE_OK:
        verdict = VERDICT_UNRESOLVED

    sources_agree = bool(data.get("sources_agree"))
    if verdict in (VERDICT_TRUE, VERDICT_FALSE) and not sources_agree:
        verdict = VERDICT_UNRESOLVED

    quote_a = str(data.get("quote_a") or "")[:280]
    quote_b = str(data.get("quote_b") or "")[:280]
    reasoning = str(data.get("reasoning") or "")[:500]

    if verdict == VERDICT_TRUE and (len(quote_a.strip()) < 8 or len(quote_b.strip()) < 8):
        verdict = VERDICT_UNRESOLVED

    return {
        "verdict": verdict,
        "source_a_status": sa,
        "source_b_status": sb,
        "sources_agree": bool(verdict != VERDICT_UNRESOLVED),
        "quote_a": quote_a,
        "quote_b": quote_b,
        "reasoning": reasoning,
    }


def _leader_resolve(claim_text: str, url_a: str, url_b: str) -> dict:
    source_a = _fetch_source(url_a)
    source_b = _fetch_source(url_b)
    return _extract_verdict(claim_text, source_a, source_b)


def _results_equivalent(leader: dict, validator: dict) -> bool:
    if not isinstance(leader, dict) or not isinstance(validator, dict):
        return False
    lv = _normalize_verdict(leader.get("verdict"))
    vv = _normalize_verdict(validator.get("verdict"))
    if lv != vv:
        return False
    if _normalize_source_status(leader.get("source_a_status")) != _normalize_source_status(
        validator.get("source_a_status")
    ):
        return False
    if _normalize_source_status(leader.get("source_b_status")) != _normalize_source_status(
        validator.get("source_b_status")
    ):
        return False
    if lv in (VERDICT_TRUE, VERDICT_FALSE):
        if _normalize_source_status(validator.get("source_a_status")) != SOURCE_OK:
            return False
        if _normalize_source_status(validator.get("source_b_status")) != SOURCE_OK:
            return False
    return True


class TwoSourceClaimResolver(gl.Contract):
    owner: Address
    next_id: u256
    claims: TreeMap[str, Claim]
    claim_ids: DynArray[str]

    def __init__(self):
        self.owner = gl.message.sender_address
        self.next_id = u256(1)

    @gl.public.write.payable
    def open_claim(
        self,
        claim_text: str,
        source_a_url: str,
        source_b_url: str,
        beneficiary: str,
        earliest_resolve_unix: int,
    ) -> str:
        text = (claim_text or "").strip()
        url_a = (source_a_url or "").strip()
        url_b = (source_b_url or "").strip()
        if len(text) < _MIN_CLAIM_LEN:
            raise gl.vm.UserError("claim_text too short")
        if not _is_http_url(url_a) or not _is_http_url(url_b):
            raise gl.vm.UserError("both sources must be http(s) URLs")
        if url_a.lower() == url_b.lower():
            raise gl.vm.UserError("sources must be independent URLs")
        if int(earliest_resolve_unix) < 0:
            raise gl.vm.UserError("earliest_resolve_unix invalid")

        claim_id = str(int(self.next_id))
        self.next_id = u256(int(self.next_id) + 1)

        ben = Address(beneficiary) if beneficiary else gl.message.sender_address
        escrow = u256(int(gl.message.value))

        self.claims[claim_id] = Claim(
            id=claim_id,
            creator=gl.message.sender_address,
            beneficiary=ben,
            claim_text=text,
            source_a_url=url_a,
            source_b_url=url_b,
            earliest_resolve_unix=u256(int(earliest_resolve_unix)),
            escrow_wei=escrow,
            status=STATUS_OPEN,
            verdict=VERDICT_UNSET,
            reasoning="",
            quote_a="",
            quote_b="",
            resolved_by=Address("0x0000000000000000000000000000000000000000"),
        )
        self.claim_ids.append(claim_id)
        return claim_id

    @gl.public.write
    def cancel_claim(self, claim_id: str) -> None:
        if claim_id not in self.claims:
            raise gl.vm.UserError("unknown claim")
        claim = self.claims[claim_id]
        if claim.creator != gl.message.sender_address:
            raise gl.vm.UserError("only creator can cancel")
        if claim.status != STATUS_OPEN:
            raise gl.vm.UserError("claim is not open")

        refund = u256(int(claim.escrow_wei))
        creator = claim.creator
        claim.status = STATUS_CANCELLED
        claim.verdict = VERDICT_UNSET
        claim.escrow_wei = u256(0)
        self.claims[claim_id] = claim
        _pay(creator, refund)

    @gl.public.write
    def resolve_claim(self, claim_id: str) -> str:
        if claim_id not in self.claims:
            raise gl.vm.UserError("unknown claim")

        stored = self.claims[claim_id]
        claim = gl.storage.copy_to_memory(stored)

        if claim.status != STATUS_OPEN:
            raise gl.vm.UserError("claim is not open")

        now = int(datetime.now(timezone.utc).timestamp())
        if now < int(claim.earliest_resolve_unix):
            raise gl.vm.UserError("too early to resolve")

        claim_text = str(claim.claim_text)
        url_a = str(claim.source_a_url)
        url_b = str(claim.source_b_url)

        def leader_fn():
            return _leader_resolve(claim_text, url_a, url_b)

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            leader_data = leader_result.calldata
            if not isinstance(leader_data, dict):
                return False
            try:
                validator_data = _leader_resolve(claim_text, url_a, url_b)
            except Exception:
                return False
            return _results_equivalent(leader_data, validator_data)

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        if not isinstance(result, dict):
            raise gl.vm.UserError("resolver returned non-object")

        verdict = _normalize_verdict(result.get("verdict"))
        stored.status = STATUS_RESOLVED
        stored.verdict = verdict
        stored.reasoning = str(result.get("reasoning") or "")[:500]
        stored.quote_a = str(result.get("quote_a") or "")[:280]
        stored.quote_b = str(result.get("quote_b") or "")[:280]
        stored.resolved_by = gl.message.sender_address

        payout = u256(int(stored.escrow_wei))
        creator = stored.creator
        beneficiary = stored.beneficiary
        stored.escrow_wei = u256(0)
        self.claims[claim_id] = stored

        if verdict == VERDICT_TRUE:
            _pay(beneficiary, payout)
        else:
            _pay(creator, payout)

        return verdict

    @gl.public.view
    def get_claim(self, claim_id: str) -> str:
        if claim_id not in self.claims:
            return json.dumps({"error": "unknown claim"})
        c = self.claims[claim_id]
        return json.dumps(
            {
                "id": c.id,
                "creator": str(c.creator),
                "beneficiary": str(c.beneficiary),
                "claim_text": c.claim_text,
                "source_a_url": c.source_a_url,
                "source_b_url": c.source_b_url,
                "earliest_resolve_unix": int(c.earliest_resolve_unix),
                "escrow_wei": int(c.escrow_wei),
                "status": c.status,
                "verdict": c.verdict,
                "reasoning": c.reasoning,
                "quote_a": c.quote_a,
                "quote_b": c.quote_b,
                "resolved_by": str(c.resolved_by),
            },
            sort_keys=True,
        )

    @gl.public.view
    def list_claim_ids(self) -> str:
        return json.dumps([cid for cid in self.claim_ids])

    @gl.public.view
    def get_next_id(self) -> str:
        return str(int(self.next_id))
