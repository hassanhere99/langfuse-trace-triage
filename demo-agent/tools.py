"""Fake in-memory bookstore backend and the tool definitions the demo agent exposes.

The tools are flawed on purpose, so the demo agent produces real failures for the
triage skill to find. Do not "fix" these without updating demo-agent/README.md and
regenerating examples/promptfoo/tools.json.

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
"""
from __future__ import annotations

import json
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

# --- Implementations --------------------------------------------------------------------

_ORDER_ID_RE = re.compile(r"^BK-\d+$")


def _err(message):
    return {"error": message}, True


def _find_order(args):
    order_id = args.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        return None, _err("Missing required argument: order_id")
    # Flaw (b): only the "BK-" prefixed form is accepted. A bare number is rejected.
    if not _ORDER_ID_RE.match(order_id):
        return None, _err(f'Invalid order_id: "{order_id}"')
    order = ORDERS.get(order_id)
    if order is None:
        return None, _err(f"Order not found: {order_id}")
    return order, None


def search_books(args):
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _err("Missing required argument: query")
    q = query.strip().lower()
    hits = [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower() or q == b["isbn"]]
    return {"query": query, "results": hits[:5], "count": len(hits[:5])}, False


def get_order_status(args):
    order, err = _find_order(args)
    if err:
        return err
    return dict(order), False


def cancel_order(args):
    order, err = _find_order(args)
    if err:
        return err
    if order["status"] != "processing":
        return _err(f"Order {order['order_id']} cannot be cancelled because its status is {order['status']}.")
    order["status"] = "cancelled"
    return {"order_id": order["order_id"], "status": "cancelled", "refund": "Full refund issued to the original payment method."}, False


def start_return(args):
    order, err = _find_order(args)
    if err:
        return err
    if order["status"] != "delivered":
        return _err(f"Order {order['order_id']} is not eligible for return because its status is {order['status']}.")
    return {
        "order_id": order["order_id"], "return_id": "RT-" + order["order_id"][3:],
        "status": "return_started", "reason": args.get("reason"),
        "next_step": "A prepaid return label has been emailed to the customer.",
    }, False


def get_store_policy(args):
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


def execute(name, args):
    """Run a tool. Returns (result_dict, is_error). Errors are {"error": "..."} with is_error True."""
    impl = _IMPLS.get(name)
    if impl is None:
        return {"error": f"Unknown tool: {name}"}, True
    if not isinstance(args, dict):
        return {"error": "Tool arguments must be an object"}, True
    return impl(args)


def reset_state():
    """Restore the in-memory orders that cancel_order mutates (used by run_demo between scenarios)."""
    for oid, status in _INITIAL_STATUS.items():
        ORDERS[oid]["status"] = status


_INITIAL_STATUS = {oid: o["status"] for oid, o in ORDERS.items()}


if __name__ == "__main__":
    if "--dump-tools" in sys.argv[1:]:
        json.dump(TOOLS, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stderr.write("usage: python demo-agent/tools.py --dump-tools > examples/promptfoo/tools.json\n")
        sys.exit(2)
