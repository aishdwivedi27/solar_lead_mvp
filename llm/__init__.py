"""LLM narrative provider selection.

Anthropic is used whenever ANTHROPIC_API_KEY is set (the local dev default).
Otherwise, if GEMINI_API_KEY is set, Gemini is used -- Gemini has a free
tier, so this is what a Render deployment should rely on. To force the
Gemini path locally (e.g. to test it before deploying), comment out
ANTHROPIC_API_KEY in .env while leaving GEMINI_API_KEY set.
"""

from config import ANTHROPIC_API_KEY, GEMINI_API_KEY, GEMINI_MODEL, logger
from llm.base import NarrativeProvider

NARRATIVE_MODEL_ANTHROPIC = "claude-opus-5"
NARRATIVE_MAX_TOKENS = 400

# Gemini 3 models spend several hundred output tokens thinking before writing the
# answer (see gemini_provider.py), so their budget needs far more headroom than
# Anthropic's for the same short narrative.
NARRATIVE_MAX_TOKENS_GEMINI = 1024


def get_narrative_provider() -> NarrativeProvider | None:
    if ANTHROPIC_API_KEY:
        from llm.anthropic_provider import AnthropicNarrativeProvider

        logger.info("Narrative provider: Anthropic (%s)", NARRATIVE_MODEL_ANTHROPIC)
        return AnthropicNarrativeProvider(
            api_key=ANTHROPIC_API_KEY,
            model=NARRATIVE_MODEL_ANTHROPIC,
            max_tokens=NARRATIVE_MAX_TOKENS,
        )

    if GEMINI_API_KEY:
        from llm.gemini_provider import GeminiNarrativeProvider

        logger.info("Narrative provider: Gemini (%s)", GEMINI_MODEL)
        return GeminiNarrativeProvider(
            api_key=GEMINI_API_KEY,
            model=GEMINI_MODEL,
            max_tokens=NARRATIVE_MAX_TOKENS_GEMINI,
        )

    logger.info("Narrative provider: none configured -- narratives will be omitted")
    return None
