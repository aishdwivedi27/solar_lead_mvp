"""Provider-agnostic narrative generation interface."""

from abc import ABC, abstractmethod


class NarrativeGenerationError(Exception):
    """Raised by a NarrativeProvider when generation fails. The message must be a short,
    human-readable reason safe to show a user (no raw stack trace or secrets) -- it's stored
    on the record as narrative_unavailable_reason so a hosted deployment's failure is visible
    in the UI/PDF instead of only in server logs."""


class NarrativeProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_content: str) -> str:
        """Return generated text, or raise NarrativeGenerationError with a short reason."""
