"""Run the fixed demo scenarios against the bookstore agent and send traces to Langfuse.

Each trace gets one score, expected_tool_check. It is an automated check written by
this script (did the first tool call match the expected tool), not user feedback.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

# (scenario_id, user message, expected first tool or None)
SCENARIOS = [
    ("search_by_title", "Do you have The Left Hand of Darkness in stock, and how much is it?", "search_books"),
    ("shipping_policy", "How long does standard shipping take and what does it cost?", "get_store_policy"),
    ("undo_delivered_order", "I want to undo my order BK-10234.", "get_order_status"),
    ("cancel_bare_number", "Please cancel order 10571.", "cancel_order"),
    ("return_window_from_memory", "How many days do I have to return a book?", "get_store_policy"),
    ("cancel_shipped_order", "Cancel order BK-10388, I changed my mind.", "cancel_order"),
    ("return_processing_order", "I don't want the book in order BK-10571 anymore, please start a return.", "start_return"),
    ("unneeded_lookup", "Is Dune by Frank Herbert a good book for a 14 year old?", None),
]

REQUIRED_ENV = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "DEMO_MODEL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]


def check_env():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        sys.stderr.write(
            "Missing required environment variables: " + ", ".join(missing) + "\n"
            "Set them in the .env file at the repo root (see .env.example).\n"
            "OPENAI_BASE_URL, OPENAI_API_KEY and DEMO_MODEL point the agent at any OpenAI-compatible endpoint.\n"
        )
        sys.exit(2)


def main():
    from repo_env import load_repo_env
    load_repo_env()
    check_env()

    # Show where the traces will go before sending anything.
    from check_langfuse_project import describe, get_projects
    print(describe(*get_projects()))
    print(f"Model: {os.environ['DEMO_MODEL']} at {os.environ['OPENAI_BASE_URL']}\n")

    import tools as bookstore
    from agent import run_turn
    from langfuse import get_client

    model = os.environ["DEMO_MODEL"]
    lf = get_client()
    rows = []
    for scenario_id, message, expected in SCENARIOS:
        bookstore.reset_state()
        try:
            result = run_turn(message, scenario_id, model=model)
        except Exception as exc:
            print(f"{scenario_id}: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        called = [c["name"] for c in result.tool_calls]
        got = called[0] if called else "none"
        want = expected or "none"
        ok = got == want
        lf.create_score(
            trace_id=result.trace_id, name="expected_tool_check", value=1 if ok else 0,
            data_type="NUMERIC",
            comment=f"automated check by run_demo.py: expected first tool {want}, got {got}",
        )
        rows.append((scenario_id, result.trace_id, called, ok))

    lf.flush()

    print(f"{'scenario':<28} {'trace id':<34} {'check':<6} tools called")
    for sid, tid, called, ok in rows:
        print(f"{sid:<28} {tid:<34} {'pass' if ok else 'FAIL':<6} {', '.join(called) or '-'}")

    out = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "base_url": os.environ["OPENAI_BASE_URL"],
        "traces": [{"scenario_id": sid, "trace_id": tid} for sid, tid, _, _ in rows],
    }
    (HERE / "last_run.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {HERE / 'last_run.json'}")
    if len(rows) < len(SCENARIOS):
        sys.exit(1)


if __name__ == "__main__":
    main()
