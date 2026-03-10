"""Configuration loaded from .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the trail project root
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")


AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Path to the JSON schema file (default: schema.json in project root)
SCHEMA_PATH = Path(os.getenv("SCHEMA_PATH", _project_root / "schema.json"))

# Resolved model defaults per provider
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.4",
    "google": "gemini-3-flash-preview",
}


def get_model() -> str:
    """Return the configured model, falling back to provider default."""
    if AI_MODEL:
        return AI_MODEL
    return _DEFAULT_MODELS.get(AI_PROVIDER, "claude-sonnet-4-6")


def get_schema() -> dict:
    """Load the JSON schema from the configured path."""
    import json
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"Schema file not found: {SCHEMA_PATH}\n"
            f"Create one or set SCHEMA_PATH in .env"
        )
    return json.loads(SCHEMA_PATH.read_text())


def get_api_key() -> str:
    """Return the API key for the configured provider."""
    keys = {
        "anthropic": ANTHROPIC_API_KEY,
        "openai": OPENAI_API_KEY,
        "google": GOOGLE_API_KEY,
    }
    key = keys.get(AI_PROVIDER, "")
    if not key:
        raise ValueError(
            f"No API key set for provider '{AI_PROVIDER}'. "
            f"Set the corresponding key in .env"
        )
    return key
