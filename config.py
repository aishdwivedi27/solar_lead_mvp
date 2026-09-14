"""Environment configuration and app-wide constants.

All `os.environ` reads for the app live here so every module has one place
to look for what's configurable and how it's sourced.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

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

MAX_FORM_ROWS = 20
