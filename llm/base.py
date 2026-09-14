"""Provider-agnostic narrative generation interface."""

from abc import ABC, abstractmethod


class NarrativeProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_content: str) -> str | None:
        """Return generated text, or None if generation failed."""
