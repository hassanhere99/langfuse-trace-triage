"""Load the repo-root .env for the demo scripts, so they never fall back to shell keys.

Values in .env override the shell. Langfuse settings are taken only from .env: any
LANGFUSE_* variable exported in the shell is dropped first. If .env is missing or does
not set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST, the scripts stop
instead of using whatever the shell exports.

Stdlib only, so check_langfuse_project.py runs before any package is installed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

sys.path.insert(0, str(ROOT / "skills" / "langfuse-trace-triage" / "scripts"))
from fetch_trace import load_env_file  # noqa: E402

REQUIRED_IN_FILE = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def load_repo_env(path: Path = ENV_PATH) -> dict:
    """Load .env into os.environ with override. Returns the values read from the file."""
    if not path.is_file():
        sys.exit(f"{path} not found. Copy .env.example to .env and fill it in. "
                 "The demo scripts do not use Langfuse keys from the shell.")
    values = load_env_file(path)
    missing = [k for k in REQUIRED_IN_FILE if not values.get(k)]
    if missing:
        sys.exit(f"{path} does not set {', '.join(missing)}. "
                 "The demo scripts do not use Langfuse keys from the shell.")
    for key in [k for k in os.environ if k.startswith("LANGFUSE_")]:
        del os.environ[key]
    os.environ.update({k: v for k, v in values.items() if v is not None})
    return values


def langfuse_host() -> str:
    return os.environ["LANGFUSE_HOST"].rstrip("/")
