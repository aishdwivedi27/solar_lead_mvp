"""Anthropic Claude narrative provider (local dev default)."""

import ssl

import anthropic

from config import logger
from llm.base import NarrativeProvider


class AnthropicNarrativeProvider(NarrativeProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int):
        # anthropic's default http client (httpx2 + truststore) hits an infinite-recursion bug
        # in truststore's Windows SSL context patch on Python 3.14; force the stdlib ssl context
        # instead of truststore's to work around it.
        self._client = anthropic.Anthropic(
            api_key=api_key,
            http_client=anthropic.DefaultHttpxClient(verify=ssl.create_default_context()),
        )
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system_prompt: str, user_content: str) -> str | None:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": user_content}],
            )
            text = "".join(block.text for block in response.content if block.type == "text").strip()
            return text or None
        except anthropic.APIError as exc:
            logger.warning("Anthropic narrative generation failed: %s", exc)
            return None
