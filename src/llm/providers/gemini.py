from google import genai
from google.genai import types


class GeminiProvider:
    DEFAULT_MODEL = "gemini-3.1-pro"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        # Usage of the most recent call_model/call_json invocation — read by
        # LLMClient.last_usage so callers can accumulate token counts.
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}

    def _record_usage(self, response) -> None:
        meta = getattr(response, "usage_metadata", None)
        self.last_usage = {
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        }

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        self._record_usage(response)
        return response.text

    def call_json(self, prompt: str, *, system: str | None = None) -> str:
        """Requests native structured JSON output. Returns the raw JSON text."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        self._record_usage(response)
        return response.text
