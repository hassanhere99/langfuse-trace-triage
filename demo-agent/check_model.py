"""Check that the endpoint and model in .env answer a tool-calling request correctly.

Sends one chat completions request with the bookstore tools and the message
"What is the status of order BK-10234?", and checks that the reply is a single
get_order_status call whose arguments are valid JSON with order_id "BK-10234".
Sends nothing to Langfuse.

Usage:
    python demo-agent/check_model.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from repo_env import load_repo_env  # noqa: E402

MESSAGE = "What is the status of order BK-10234?"


def main():
    load_repo_env()
    import tools as bookstore
    from agent import SYSTEM_PROMPT, make_client

    model = os.environ.get("DEMO_MODEL")
    client = make_client()
    print(f"Model {model} at {os.environ['OPENAI_BASE_URL']}")
    start = time.monotonic()
    response = client.chat.completions.create(
        model=model, temperature=0, max_tokens=1024, tools=bookstore.TOOLS,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": MESSAGE}],
    )
    elapsed = time.monotonic() - start
    message = response.choices[0].message
    calls = message.tool_calls or []
    print(f"Answered in {elapsed:.1f}s, finish_reason={response.choices[0].finish_reason}")
    print("Text:", repr((message.content or "")[:300]))
    problems = []
    for tc in calls:
        print(f"Tool call: {tc.function.name}({tc.function.arguments})")
    if len(calls) != 1:
        problems.append(f"expected exactly 1 tool call, got {len(calls)}")
    else:
        tc = calls[0]
        try:
            args = json.loads(tc.function.arguments or "")
        except json.JSONDecodeError as exc:
            args = None
            problems.append(f"arguments are not valid JSON: {exc}")
        if tc.function.name != "get_order_status":
            problems.append(f"expected get_order_status, got {tc.function.name}")
        if isinstance(args, dict) and args.get("order_id") != "BK-10234":
            problems.append(f"expected order_id BK-10234, got {args.get('order_id')!r}")
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    print("PASS: valid get_order_status call with order_id BK-10234")


if __name__ == "__main__":
    main()
