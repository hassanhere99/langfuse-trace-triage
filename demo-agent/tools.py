"""Fake in-memory bookstore backend and the tool definitions the demo agent exposes.

The tools are flawed on purpose, so the demo agent produces real failures for the
triage skill to find. The flawed behaviour is the default and must stay reproducible: it is
what examples/ was generated from. Do not edit it without updating demo-agent/README.md and
regenerating examples/promptfoo/tools.json.

Variants (AGENT_VARIANT=flawed|fixed|desc_only|errors_only, default flawed)
    flawed       the tools exactly as the committed examples were generated.
    fixed        two changes, nothing else:
                 1. the order_id description of every tool that takes one states the format
                    (BK- followed by 5 digits, e.g. BK-10571);
                 2. error messages say what to do next, not only what failed.
    desc_only    change 1 only, with the flawed error messages.
    errors_only  change 2 only, with the flawed order_id description.
    The cancel_order / start_return description overlap (flaw a) is NOT fixed in any variant. It
    is the control of the experiment. The search_books matching limitation is not fixed either
    (see experiments/discovered_bugs.md).

Deliberate flaws:

(a) Overlapping descriptions. cancel_order and start_return are both described
    vaguely as undoing or reversing an order. Neither description says that
    cancel_order only works on orders that have not shipped, or that start_return
    only works on delivered orders.

(b) Underspecified argument. The order_id argument is described only as
    "The order ID". The server accepts only the "BK-" prefixed form (BK-10234) and
    returns an error for a bare number such as 10234.

Server behaviour that makes the flaws visible:
    cancel_order on a shipped or delivered order returns an error.
    start_return on a processing or shipped order returns an error.

Usage:
    python demo-agent/tools.py --dump-tools > examples/promptfoo/tools.json
    python demo-agent/tools.py --dump-tools --variant fixed|desc_only|errors_only
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys

BOOKS = [
    {"isbn": "9780441478125", "title": "The Left Hand of Darkness", "author": "Ursula K. Le Guin", "price": 11.99, "stock": 14},
    {"isbn": "9780441172719", "title": "Dune", "author": "Frank Herbert", "price": 12.99, "stock": 22},
    {"isbn": "9780143127741", "title": "The Remains of the Day", "author": "Kazuo Ishiguro", "price": 14.50, "stock": 0},
    {"isbn": "9780062315007", "title": "The Alchemist", "author": "Paulo Coelho", "price": 10.99, "stock": 31},
    {"isbn": "9780374533557", "title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "price": 18.00, "stock": 6},
    {"isbn": "9780307474278", "title": "The Girl with the Dragon Tattoo", "author": "Stieg Larsson", "price": 13.25, "stock": 9},
    {"isbn": "9780525559474", "title": "The Midnight Library", "author": "Matt Haig", "price": 16.99, "stock": 17},
]

ORDERS = {
    "BK-10234": {
        "order_id": "BK-10234", "customer_email": "ana.silva@example.com", "status": "delivered",
        "items": [{"isbn": "9780441172719", "title": "Dune", "quantity": 1}],
        "ordered": "2026-11-02", "shipped": "2026-11-04", "delivered": "2026-11-09", "total": 12.99,
    },
    "BK-10388": {
        "order_id": "BK-10388", "customer_email": "tom.becker@example.com", "status": "shipped",
        "items": [{"isbn": "9780374533557", "title": "Thinking, Fast and Slow", "quantity": 1},
                  {"isbn": "9780062315007", "title": "The Alchemist", "quantity": 2}],
        "ordered": "2026-11-18", "shipped": "2026-11-21", "delivered": None, "total": 40.00,
    },
    "BK-10571": {
        "order_id": "BK-10571", "customer_email": "priya.nair@example.com", "status": "processing",
        "items": [{"isbn": "9780525559474", "title": "The Midnight Library", "quantity": 1}],
        "ordered": "2026-11-23", "shipped": None, "delivered": None, "total": 16.99,
    },
    "BK-10602": {
        "order_id": "BK-10602", "customer_email": "li.wei@example.com", "status": "processing",
        "items": [{"isbn": "9780441478125", "title": "The Left Hand of Darkness", "quantity": 1}],
        "ordered": "2026-11-24", "shipped": None, "delivered": None, "total": 11.99,
    },
    "BK-10107": {
        "order_id": "BK-10107", "customer_email": "sam.ortiz@example.com", "status": "delivered",
        "items": [{"isbn": "9780307474278", "title": "The Girl with the Dragon Tattoo", "quantity": 1}],
        "ordered": "2026-10-05", "shipped": "2026-10-07", "delivered": "2026-10-12", "total": 13.25,
    },
}

POLICIES = {
    "returns": (
        "Books can be returned within 30 days of delivery if they are in their original condition. "
        "Returns can only be started for orders that have been delivered. Refunds go to the original "
        "payment method within 5 to 7 business days after we receive the book."
    ),
    "shipping": (
        "Standard shipping takes 3 to 5 business days and costs $4.50. Orders over $35 ship free. "
        "Express shipping takes 1 to 2 business days and costs $12.00. We ship within the United States only."
    ),
    "cancellations": (
        "An order can be cancelled only while its status is processing. Once an order has shipped it "
        "cannot be cancelled; after it is delivered the customer can start a return instead."
    ),
}

# --- Tool definitions (OpenAI chat completions format) ----------------------------------


def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOLS = [
    _tool(
        "search_books",
        "Search the bookstore catalog by title, author or ISBN. Returns up to five matching books "
        "with ISBN, title, author, price in USD and the number of copies in stock.",
        {"query": {"type": "string", "description": "A title, author name or ISBN to search for."}},
        ["query"],
    ),
    _tool(
        "get_order_status",
        "Look up an order and return its status, items and key dates.",
        # Flaw (b): the format is not stated.
        {"order_id": {"type": "string", "description": "The order ID"}},
        ["order_id"],
    ),
    # Flaw (a): overlaps with start_return, and does not say it only works before shipping.
    _tool(
        "cancel_order",
        "Undo an order. Use this when the customer wants to reverse or back out of an order they placed.",
        {"order_id": {"type": "string", "description": "The order ID"}},
        ["order_id"],
    ),
    # Flaw (a): overlaps with cancel_order, and does not say it only works after delivery.
    _tool(
        "start_return",
        "Reverse an order. Use this when the customer wants to undo a purchase and get their money back.",
        {
            "order_id": {"type": "string", "description": "The order ID"},
            "reason": {"type": "string", "description": "Why the customer wants to return the order."},
        },
        ["order_id"],
    ),
    _tool(
        "get_store_policy",
        "Return the official store policy text for one topic: returns, shipping or cancellations. "
        "Use it for questions about how the store's rules work rather than about a specific order.",
        {"topic": {"type": "string", "enum": ["returns", "shipping", "cancellations"],
                   "description": "The policy topic to look up."}},
        ["topic"],
    ),
]

# --- Variants ---------------------------------------------------------------------------

# variant -> (fix 1: order_id description, fix 2: error messages)
_VARIANT_FIXES = {
    "flawed": (False, False),
    "fixed": (True, True),
    "desc_only": (True, False),
    "errors_only": (False, True),
}
VARIANTS = tuple(_VARIANT_FIXES)
ORDER_ID_FIXED = "The order ID. Format: BK- followed by 5 digits, e.g. BK-10571."


def resolve_variant(value=None):
    """The variant to use: the argument, else AGENT_VARIANT from the environment, else flawed."""
    raw = value if value is not None else os.environ.get("AGENT_VARIANT")
    variant = (raw or "flawed").strip().lower()
    if variant not in VARIANTS:
        raise ValueError(f"AGENT_VARIANT must be one of {', '.join(VARIANTS)}, got {raw!r}")
    return variant


def tools_for(variant=None):
    """Tool definitions for a variant. Without fix 1 this is TOOLS itself; otherwise a modified copy."""
    if not _VARIANT_FIXES[resolve_variant(variant)][0]:
        return TOOLS
    fixed = copy.deepcopy(TOOLS)
    for tool in fixed:
        props = tool["function"]["parameters"]["properties"]
        if "order_id" in props:
            props["order_id"]["description"] = ORDER_ID_FIXED
    return fixed


# --- Implementations --------------------------------------------------------------------

_ORDER_ID_RE = re.compile(r"^BK-\d+$")


def _err(message):
    return {"error": message}, True


# In the implementations below, `fixed` means "fix 2 is on": errors say what to do next.
def _find_order(args, fixed):
    order_id = args.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        msg = "Missing required argument: order_id"
        if fixed:
            msg += ". Pass the order ID: BK- followed by 5 digits, e.g. BK-10571."
        return None, _err(msg)
    # Flaw (b): only the "BK-" prefixed form is accepted. A bare number is rejected.
    if not _ORDER_ID_RE.match(order_id):
        msg = f'Invalid order_id: "{order_id}"'
        if fixed:
            msg += ". Order IDs are BK- followed by 5 digits, e.g. BK-10571."
        return None, _err(msg)
    order = ORDERS.get(order_id)
    if order is None:
        msg = f"Order not found: {order_id}"
        if fixed:
            msg += ". Check the order ID with the customer and try again."
        return None, _err(msg)
    return order, None


def search_books(args, fixed=False):
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        msg = "Missing required argument: query"
        if fixed:
            msg += ". Pass a title, author name or ISBN."
        return _err(msg)
    q = query.strip().lower()
    hits = [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower() or q == b["isbn"]]
    return {"query": query, "results": hits[:5], "count": len(hits[:5])}, False


def get_order_status(args, fixed=False):
    order, err = _find_order(args, fixed)
    if err:
        return err
    return dict(order), False


# fixed variant: what the customer or agent can do next, by order status
_CANCEL_NEXT = {
    "shipped": "Order {id} has shipped, so it can't be cancelled. A return can be started once it has been delivered.",
    "delivered": "Order {id} has been delivered, so it can't be cancelled. It can be returned instead with start_return.",
    "cancelled": "Order {id} is already cancelled. No further action is needed.",
}
_RETURN_NEXT = {
    "processing": "Order {id} has not shipped, so it can't be returned. It can be cancelled instead with cancel_order.",
    "shipped": "Order {id} has shipped but has not been delivered, so it can't be returned yet. A return can be started once it has been delivered.",
    "cancelled": "Order {id} was cancelled, so it can't be returned. No further action is needed.",
}


def cancel_order(args, fixed=False):
    order, err = _find_order(args, fixed)
    if err:
        return err
    if order["status"] != "processing":
        if fixed and order["status"] in _CANCEL_NEXT:
            return _err(_CANCEL_NEXT[order["status"]].format(id=order["order_id"]))
        return _err(f"Order {order['order_id']} cannot be cancelled because its status is {order['status']}.")
    order["status"] = "cancelled"
    return {"order_id": order["order_id"], "status": "cancelled", "refund": "Full refund issued to the original payment method."}, False


def start_return(args, fixed=False):
    order, err = _find_order(args, fixed)
    if err:
        return err
    if order["status"] != "delivered":
        if fixed and order["status"] in _RETURN_NEXT:
            return _err(_RETURN_NEXT[order["status"]].format(id=order["order_id"]))
        return _err(f"Order {order['order_id']} is not eligible for return because its status is {order['status']}.")
    return {
        "order_id": order["order_id"], "return_id": "RT-" + order["order_id"][3:],
        "status": "return_started", "reason": args.get("reason"),
        "next_step": "A prepaid return label has been emailed to the customer.",
    }, False


def get_store_policy(args, fixed=False):
    topic = args.get("topic")
    if topic not in POLICIES:
        return _err(f"Unknown policy topic: {topic!r}. Valid topics: {', '.join(POLICIES)}")
    return {"topic": topic, "policy": POLICIES[topic]}, False


_IMPLS = {
    "search_books": search_books,
    "get_order_status": get_order_status,
    "cancel_order": cancel_order,
    "start_return": start_return,
    "get_store_policy": get_store_policy,
}


def execute(name, args, variant=None):
    """Run a tool. Returns (result_dict, is_error). Errors are {"error": "..."} with is_error True.

    variant is one of VARIANTS; None means AGENT_VARIANT from the environment, default flawed.
    """
    fixed = _VARIANT_FIXES[resolve_variant(variant)][1]  # the "fixed" flag in the impls means fix 2
    impl = _IMPLS.get(name)
    if impl is None:
        msg = f"Unknown tool: {name}"
        if fixed:
            msg += f". Available tools: {', '.join(_IMPLS)}."
        return {"error": msg}, True
    if not isinstance(args, dict):
        msg = "Tool arguments must be an object"
        if fixed:
            msg += ', for example {"query": "Dune"}.'
        return {"error": msg}, True
    return impl(args, fixed)


def reset_state():
    """Restore the in-memory orders that cancel_order mutates (used by run_demo between scenarios)."""
    for oid, status in _INITIAL_STATUS.items():
        ORDERS[oid]["status"] = status


_INITIAL_STATUS = {oid: o["status"] for oid, o in ORDERS.items()}


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--dump-tools" in argv:
        variant = argv[argv.index("--variant") + 1] if "--variant" in argv[:-1] else "flawed"
        json.dump(tools_for(variant), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stderr.write("usage: python demo-agent/tools.py --dump-tools [--variant flawed|fixed|desc_only|errors_only] > tools.json\n")
        sys.exit(2)
