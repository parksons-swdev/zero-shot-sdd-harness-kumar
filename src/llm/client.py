import json

from config.settings import get_settings

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

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        return self._provider.call_model(prompt, system=system)

    def call_json(self, prompt: str, *, system: str | None = None) -> dict:
        """Requests structured JSON output and parses it into a dict.

        Uses the provider's native JSON mode when available
        (`call_json` on the provider); otherwise falls back to asking for
        JSON in prose and parsing the (possibly fenced) response text.
        """
        if hasattr(self._provider, "call_json"):
            raw = self._provider.call_json(prompt, system=system)
        else:
            json_system = (system or "") + "\n\nRespond with ONLY valid JSON. No prose, no markdown fences."
            raw = self._provider.call_model(prompt, system=json_system.strip())

        cleaned = _strip_code_fence(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {exc}. Raw output: {raw[:500]!r}") from exc
