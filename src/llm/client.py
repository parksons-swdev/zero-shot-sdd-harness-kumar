import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

from config.settings import get_settings
from observability.events import get_logger

log = get_logger("llm")

T = TypeVar("T")

# Published per-token pricing (USD per 1M tokens), used to compute
# `estimated_cost_usd` (spec/data.md). Approximate list-price rates as of
# this build; update if a provider changes pricing. Unknown models fall back
# to the "gemini-2.5-flash" rate as a conservative estimate.
_PRICING_PER_MILLION_TOKENS = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-flash-latest": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 10.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}
_DEFAULT_PRICING = _PRICING_PER_MILLION_TOKENS["gemini-2.5-flash"]


def estimate_cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Computes estimated cost from token counts and published per-token
    pricing (spec/data.md: `estimated_cost_usd` "Computed from token counts
    and published per-token pricing")."""
    rates = _PRICING_PER_MILLION_TOKENS.get(model or "", _DEFAULT_PRICING)
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


class LLMQuotaError(RuntimeError):
    """A call failed on a quota/auth condition (e.g. HTTP 429
    RESOURCE_EXHAUSTED, or 401/403 auth). These FAIL FAST — retrying a quota
    that is already exhausted only makes the throttling worse. Carries a
    clear, actionable message for the caller/user."""


class LLMTransientError(RuntimeError):
    """A call exhausted its transient-failure retries (per-call timeout / 5xx
    / network). Raised after the configured backoff attempts are used up."""


# HTTP status classification. Kept as duck-typed status-code / message checks
# so this provider-agnostic client works for both Gemini (google.genai
# APIError, which exposes `.code`) and Anthropic without importing either
# SDK's error module here.
_QUOTA_CODES = {429}
_AUTH_CODES = {401, 403}
_TRANSIENT_CODES = {500, 502, 503, 504}

_QUOTA_MARKERS = ("resource_exhausted", "quota", "rate limit", "rate_limit", "too many requests")
_AUTH_MARKERS = ("unauthenticated", "permission_denied", "permission denied", "api key", "api_key", "invalid authentication")
_TRANSIENT_MARKERS = ("timeout", "timed out", "deadline", "unavailable", "temporarily", "connection", "connect", "reset by peer", "502", "503", "504")


def _status_code(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def _classify_error(exc: BaseException) -> str:
    """Returns one of: 'quota' | 'auth' | 'transient' | 'fatal'.

    Quota (429) and auth (401/403) FAIL FAST. Transient (timeouts, 5xx,
    network) are retried with backoff. Everything else is fatal and re-raised
    unchanged.
    """
    code = _status_code(exc)
    msg = str(exc).lower()

    # A hung call that hit the per-call wall-clock timeout is transient.
    if isinstance(exc, (FutureTimeoutError, TimeoutError)):
        return "transient"

    if code in _QUOTA_CODES or any(m in msg for m in _QUOTA_MARKERS):
        return "quota"
    if code in _AUTH_CODES or any(m in msg for m in _AUTH_MARKERS):
        return "auth"
    if code in _TRANSIENT_CODES or any(m in msg for m in _TRANSIENT_MARKERS):
        return "transient"
    return "fatal"


def _make_provider(model_override: str | None = None):
    s = get_settings()
    provider = s.llm_provider

    # auto-detect from whichever key is set
    if not provider:
        if s.anthropic_api_key:
            provider = "anthropic"
        elif s.gemini_api_key:
            provider = "gemini"
        else:
            raise RuntimeError(
                "No LLM provider configured. Set AGENT_ANTHROPIC_API_KEY or "
                "AGENT_GEMINI_API_KEY in .env, or set AGENT_LLM_PROVIDER explicitly."
            )

    model = model_override or s.llm_model

    if provider == "anthropic":
        from llm.providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=s.anthropic_api_key, model=model)
    if provider == "gemini":
        from llm.providers.gemini import GeminiProvider
        return GeminiProvider(api_key=s.gemini_api_key, model=model)

    raise RuntimeError(f"Unknown LLM provider: {provider!r}. Supported: anthropic, gemini")


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class LLMClient:
    """Single choke point for every Gemini (or Anthropic) call.

    `model` selects which of the two model tiers (`AGENT_LLM_MODEL_FAST` /
    `AGENT_LLM_MODEL_QUALITY`) this instance uses — callers pass the
    resolved model id in, this class does not know about tiers itself.
    """

    def __init__(self, model: str | None = None) -> None:
        self._provider = _make_provider(model)
        self.model = model

    @property
    def last_usage(self) -> dict:
        """Token usage of the most recent call_model/call_json call on this
        client, as `{"input_tokens": int, "output_tokens": int}`."""
        return getattr(self._provider, "last_usage", {"input_tokens": 0, "output_tokens": 0})

    def _run_with_resilience(self, fn: "Callable[[], T]", *, label: str) -> "T":
        """Runs `fn` (a single provider call) under a per-call wall-clock
        timeout with exponential-backoff retry for TRANSIENT failures only.

        - transient (timeout / 5xx / network): retried up to
          `llm_max_retries` with backoff `base * 2**(n-1)`.
        - quota (429 RESOURCE_EXHAUSTED) / auth (401/403): FAIL FAST — never
          retried; re-raised as `LLMQuotaError` with an actionable message.
        - anything else: re-raised unchanged (fatal).
        """
        s = get_settings()
        timeout = s.llm_timeout_seconds
        max_retries = s.llm_max_retries
        backoff_base = s.llm_backoff_base_seconds

        attempt = 0
        while True:
            try:
                # The per-call timeout guards against a hung provider call
                # eating the whole 30s run budget. On timeout the underlying
                # request is abandoned (thread is left to finish) and the
                # timeout is classified as transient below.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(fn).result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                kind = _classify_error(exc)
                if kind == "quota":
                    log.error("llm_quota_error", label=label, model=self.model, error=str(exc)[:300])
                    raise LLMQuotaError(
                        "Gemini quota exhausted (HTTP 429 RESOURCE_EXHAUSTED): this API "
                        "key has no remaining quota for the requested model. This is NOT "
                        "retried — wait for the quota window to reset or upgrade the billing "
                        "plan / choose a model with available quota."
                    ) from exc
                if kind == "auth":
                    log.error("llm_auth_error", label=label, model=self.model, error=str(exc)[:300])
                    raise LLMQuotaError(
                        "Gemini authentication/permission error: check AGENT_GEMINI_API_KEY "
                        "in .env. This is NOT retried."
                    ) from exc
                if kind != "transient":
                    raise
                attempt += 1
                if attempt > max_retries:
                    log.error(
                        "llm_transient_exhausted",
                        label=label, model=self.model, attempts=attempt, error=str(exc)[:300],
                    )
                    raise LLMTransientError(
                        f"Gemini call failed after {attempt} attempt(s) due to transient "
                        f"errors (timeout / 5xx / network): {exc}"
                    ) from exc
                sleep_s = backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "llm_transient_retry",
                    label=label, model=self.model, attempt=attempt, sleep_s=sleep_s, error=str(exc)[:200],
                )
                time.sleep(sleep_s)

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        return self._run_with_resilience(
            lambda: self._provider.call_model(prompt, system=system), label="call_model"
        )

    def call_json(self, prompt: str, *, system: str | None = None) -> dict:
        """Requests structured JSON output and parses it into a dict.

        Uses the provider's native JSON mode when available
        (`call_json` on the provider); otherwise falls back to asking for
        JSON in prose and parsing the (possibly fenced) response text.

        The network call is wrapped in the timeout/backoff resilience layer;
        JSON parsing happens AFTER (outside) the retry loop — a malformed-JSON
        response is not a transient network condition, so it raises `ValueError`
        and is handled as a retryable *reasoning* failure by the graph
        (generate_code feeds it back into the observe/decide loop), not by a
        network retry here.
        """
        raw = self._run_with_resilience(lambda: self._raw_json(prompt, system=system), label="call_json")

        cleaned = _strip_code_fence(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {exc}. Raw output: {raw[:500]!r}") from exc

    def _raw_json(self, prompt: str, *, system: str | None = None) -> str:
        if hasattr(self._provider, "call_json"):
            return self._provider.call_json(prompt, system=system)
        json_system = (system or "") + "\n\nRespond with ONLY valid JSON. No prose, no markdown fences."
        return self._provider.call_model(prompt, system=json_system.strip())
