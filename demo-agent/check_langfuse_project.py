"""Print which Langfuse project the keys in the repo-root .env belong to.

Prints the host, project name and project ID. Never prints the keys.
Run it before run_demo.py to make sure traces go to the project you expect.

Usage:
    python3 demo-agent/check_langfuse_project.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_env import load_repo_env, langfuse_host  # noqa: E402


def get_projects():
    """Return (host, [project dicts]) for the keys in .env. Exits on error."""
    from fetch_trace import FetchError, api_get

    load_repo_env()
    host = langfuse_host()
    try:
        data = api_get(host, "/api/public/projects", [],
                       os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    except FetchError as exc:
        sys.exit(str(exc))
    return host, data.get("data") or []


def describe(host, projects):
    lines = [f"Langfuse host: {host}"]
    for p in projects:
        org = (p.get("organization") or {}).get("name")
        lines.append(f"Project: {p.get('name')}  (id {p.get('id')})" + (f", organization {org}" if org else ""))
    if not projects:
        lines.append("No project returned for these keys.")
    return "\n".join(lines)


def main():
    host, projects = get_projects()
    print(describe(host, projects))
    sys.exit(0 if projects else 1)


if __name__ == "__main__":
    main()
