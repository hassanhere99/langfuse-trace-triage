"""List every error message that the fixed / errors_only variants change, before -> after.

    python experiments/error_changes.py             # prints a Markdown table

PROBES covers every error return in demo-agent/tools.py. Each probe is one call that triggers one
error. Some error sites produce several messages (one per order status); those are separate
probes under the same site number. The tests check that desc_only changes none of these and that
errors_only changes exactly the same ones as fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo-agent"))

import tools  # noqa: E402


def _cancel_first(order_id):
    def setup(variant):
        tools.execute("cancel_order", {"order_id": order_id}, variant)
    return setup


# (site number, short name, tool, args, setup(variant) or None)
PROBES = [
    (1, "missing order_id", "get_order_status", {}, None),
    (2, "invalid order_id (bare number)", "cancel_order", {"order_id": "10571"}, None),
    (3, "order not found", "get_order_status", {"order_id": "BK-99999"}, None),
    (4, "cancel_order, order shipped", "cancel_order", {"order_id": "BK-10388"}, None),
    (4, "cancel_order, order delivered", "cancel_order", {"order_id": "BK-10234"}, None),
    (4, "cancel_order, order already cancelled", "cancel_order", {"order_id": "BK-10571"}, _cancel_first("BK-10571")),
    (5, "start_return, order processing", "start_return", {"order_id": "BK-10571"}, None),
    (5, "start_return, order shipped", "start_return", {"order_id": "BK-10388"}, None),
    (5, "start_return, order cancelled", "start_return", {"order_id": "BK-10571"}, _cancel_first("BK-10571")),
    (6, "missing query", "search_books", {}, None),
    (7, "unknown tool", "no_such_tool", {}, None),
    (8, "arguments not an object", "search_books", [], None),
]

# Error returns that no variant changes (already said what to do next).
UNCHANGED_PROBES = [
    ("unknown policy topic", "get_store_policy", {"topic": "refunds"}, None),
]


def run_probe(variant, tool, args, setup):
    tools.reset_state()
    try:
        if setup:
            setup(variant)
        result, is_error = tools.execute(tool, args, variant)
    finally:
        tools.reset_state()
    assert is_error, f"{tool} {args} did not error under {variant}: {result}"
    return result["error"]


def error_changes(before="flawed", after="fixed"):
    """Rows (site, name, tool, args, before_text, after_text) for every probe."""
    return [
        (site, name, tool, args, run_probe(before, tool, args, setup), run_probe(after, tool, args, setup))
        for site, name, tool, args, setup in PROBES
    ]


def render_table(before="flawed", after="fixed"):
    rows = error_changes(before, after)
    sites = len({r[0] for r in rows})
    out = [
        f"{sites} error sites in `demo-agent/tools.py` change, which is {len(rows)} concrete messages "
        "(sites 4 and 5 have one message per order status):\n",
        "| # | Error | Before (`flawed`) | After (`fixed` and `errors_only`) |",
        "|---|---|---|---|",
    ]
    for site, name, _tool, _args, b, a in rows:
        out.append(f"| {site} | {name} | `{b}` | `{a}` |")
    out.append("")
    for name, tool, args, setup in UNCHANGED_PROBES:
        same = run_probe(before, tool, args, setup) == run_probe(after, tool, args, setup)
        out.append(f"Not changed: {name} (`{run_probe(before, tool, args, setup)}`), identical in both: {same}.")
    out.append(
        "\nTwo errors raised by `demo-agent/agent.py` itself (arguments that are not valid JSON, or not a JSON "
        "object) are not changed in any variant."
    )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render_table())
