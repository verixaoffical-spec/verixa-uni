"""Verixa backend.

`.env` is loaded here, before any submodule reads a setting.

The Official UI alone did not need this: pydantic-settings reads `.env` into the `settings` object
by itself. The Analysis Agent does need it, because it and litellm read provider keys and model
chains straight from `os.environ` (GROQ_API_KEY, OPENROUTER_API_KEY, ANALYSIS_MODELS,
HIGH_RISK_KEYWORDS, ...). Loading the file into the process environment once, here, is what lets
one `.env` serve the app and the agent.

`override=False` means a variable already set in the real environment wins, so the test suite and
CI can set DATABASE_URL without `.env` quietly replacing it.
"""
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # python-dotenv missing: real environment variables still work
    pass
