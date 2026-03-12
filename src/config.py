"""Configuration loaded from .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the trail project root
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

_VALID_PROVIDERS = {"anthropic", "openai", "google", "ollama"}

AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")

if AI_PROVIDER not in _VALID_PROVIDERS:
    raise ValueError(
        f"Invalid AI_PROVIDER='{AI_PROVIDER}'. "
        f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}"
    )

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Ollama configuration — uses OpenAI-compatible API
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.9:11434")

# Path to the JSON schema file (default: schema.json in project root)
SCHEMA_PATH = Path(os.getenv("SCHEMA_PATH", _project_root / "schema.json"))

# Path to the system prompt file (default: prompt.txt in project root)
PROMPT_PATH = Path(os.getenv("PROMPT_PATH", _project_root / "prompt.txt"))

# Resolved model defaults per provider
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.4",
    "google": "gemini-3-flash-preview",
    "ollama": "qwen3-vl:32b",
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


def get_system_prompt() -> str:
    """Load the system prompt from the configured path."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {PROMPT_PATH}\n"
            f"Create one or set PROMPT_PATH in .env"
        )
    return PROMPT_PATH.read_text().strip()


def get_api_key() -> str:
    """Return the API key for the configured provider.

    Ollama runs locally and does not require an API key.
    """
    if AI_PROVIDER == "ollama":
        return "ollama"  # placeholder — Ollama needs no auth
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
