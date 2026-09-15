"""Google Gemini narrative provider (Render deployment default -- has a free tier)."""

from config import logger
from llm.base import NarrativeGenerationError, NarrativeProvider


class GeminiNarrativeProvider(NarrativeProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system_prompt: str, user_content: str) -> str:
        from google.genai import types

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self._max_tokens,
                    # Gemini 3 models think before answering and cannot fully disable it
                    # (thinking_budget=0 is rejected); "low" keeps that overhead down, and
                    # max_tokens must stay well above what a short narrative alone needs
                    # to leave room for the thinking tokens spent ahead of the answer.
                    thinking_config=types.ThinkingConfig(thinking_level="low"),
                ),
            )
            text = (response.text or "").strip()
        except Exception as exc:  # google-genai's error taxonomy isn't narrow enough to enumerate here
            logger.warning("Gemini narrative generation failed: %s", exc)
            raise NarrativeGenerationError(f"Gemini API error: {exc}") from exc

        if not text:
            raise NarrativeGenerationError("Gemini returned an empty response")
        return text
