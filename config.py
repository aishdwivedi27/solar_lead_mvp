"""Environment configuration and app-wide constants.

All `os.environ` reads for the app live here so every module has one place
to look for what's configurable and how it's sourced.
"""

import logging
import os

import truststore
from dotenv import load_dotenv

load_dotenv()

# Makes Python's ssl module verify certificates against the OS trust store
# instead of the certifi-bundled CA list. Needed because SSL-inspecting
# antivirus/corporate proxies (e.g. Norton's "Web/Mail Shield") re-sign
# outbound HTTPS with a locally-generated root CA that Windows trusts but
# certifi doesn't ship, which otherwise makes every httpx geocoding request
# fail with CERTIFICATE_VERIFY_FAILED on an affected machine. A no-op on
# machines/platforms without such interception, so this is safe on Render too.
truststore.inject_into_ssl()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("solar_lead_mvp")

COPERNICUS_CLIENT_ID = os.environ.get("COPERNICUS_CLIENT_ID")
COPERNICUS_CLIENT_SECRET = os.environ.get("COPERNICUS_CLIENT_SECRET")

# LLM narrative provider selection: Anthropic is used whenever a key is
# present (the local dev default); Gemini -- which has a free tier -- is
# used otherwise, which is what Render deployments should rely on. Leaving
# ANTHROPIC_API_KEY unset/commented-out in .env (even locally) falls through
# to Gemini, which is the documented way to test the Gemini path locally.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# Nominatim usage policy asks for a real identifying User-Agent, ideally with
# a contact point. Read the contact from the environment rather than
# hardcoding a personal email address.
NOMINATIM_CONTACT = os.environ.get("NOMINATIM_CONTACT_EMAIL", "contact not set")
NOMINATIM_USER_AGENT = f"solar_lead_mvp/0.1 ({NOMINATIM_CONTACT})"

# OpenCage Geocoding API: rooftop-level fallback used when Nominatim
# (OpenStreetMap data) only resolves an address to a road. Optional -- the
# fallback is skipped when unset, matching Nominatim-only behavior. Free
# trial signup (https://opencagedata.com) needs no credit card; its own cap
# is 2,500 requests/day, so OPENCAGE_DAILY_REQUEST_LIMIT defaults well under
# that.
OPENCAGE_API_KEY = os.environ.get("OPENCAGE_API_KEY", "").strip()
OPENCAGE_DAILY_REQUEST_LIMIT = int(os.environ.get("OPENCAGE_DAILY_REQUEST_LIMIT", "1500"))

MAX_FORM_ROWS = 20


class _RedactSecretsFilter(logging.Filter):
    """Scrubs configured secret values out of every log record before it's
    emitted, wherever in the message they show up -- e.g. OpenCage's API key
    rides along in the query string of every geocode request, and httpx logs
    that full URL (querystring included) at INFO level by default. Attached
    to the root logger's handlers rather than to individual loggers, so it
    still catches records from httpx/httpcore (or any other library that
    ends up logging a URL, header, or payload containing one of these
    values), not just our own "solar_lead_mvp" logger -- and applies the
    same locally and on Render, since both go through this same setup."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            for secret in self._secrets:
                if secret in message:
                    message = message.replace(secret, "***REDACTED***")
            record.msg = message
            record.args = None
        return True


_redact_secrets_filter = _RedactSecretsFilter(
    [COPERNICUS_CLIENT_ID, COPERNICUS_CLIENT_SECRET, ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENCAGE_API_KEY]
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_redact_secrets_filter)
