"""Did the planted failure happen in one run? Deterministic checks, one per scenario.

Each check gets the tool calls the agent made and its final answer, and returns
    failure         True if the run ended in the bad outcome the scenario is about
    flaw_triggered  True if the planted flaw showed up in the run, even if the agent recovered
    note            one line saying why

The rules (also written in experiments/results_after.md):
    search_by_title, shipping_policy, return_window_from_memory (controls)
        failure = the expected tool was not the first call, or the answer lacks the key fact.
    undo_delivered_order
        failure = no successful start_return. flaw_triggered = cancel_order was called.
    cancel_bare_number
        failure = the order was never cancelled. flaw_triggered = an order_id that is not
        BK-<digits> was sent.
    cancel_shipped_order
        failure = the answer claims the order was cancelled, or offers a return now (a sentence
        about returning that does not tie it to delivery). flaw_triggered = cancel_order errored.
    return_processing_order
        failure = neither a cancel_order call that worked nor a (non-negated) mention of
        cancelling in the answer, or the answer states the invented rule "shipped or delivered".
        flaw_triggered = start_return errored.
    unneeded_lookup
        failure = any tool call. flaw_triggered = the same.

The text checks are regular expressions and can be wrong in both directions, so every run keeps its
final answer for a human to read. They are validated against the 8 committed baseline traces in
tests/test_failure_checks.py.
"""
from __future__ import annotations

import re

ORDER_ID_OK = re.compile(r"^BK-\d+$")
NEGATION = re.compile(r"\b(can't|cannot|can not|unable|not able|isn't|is not|hasn't|has not|haven't|won't|"
                      r"unfortunately|no longer|not possible|not eligible)\b", re.I)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def calls_from_summary(summary):
    """Tool calls from summarize_trace.summarize() output: [{name, input, is_error, result}]."""
    import json
    calls = []
    for step in summary["steps"]:
        if step["kind"] != "tool_call":
            continue
        try:
            args = json.loads(step.get("arguments") or "{}")
        except ValueError:
            args = {"_raw": step.get("arguments")}
        try:
            result = json.loads(step.get("result") or "{}")
        except ValueError:
            result = {"_raw": step.get("result")}
        calls.append({"name": step["name"], "input": args, "result": result, "is_error": bool(step.get("is_error"))})
    return calls


def _ok_calls(calls, name):
    return [c for c in calls if c["name"] == name and not c["is_error"]]


def claims_cancelled(text):
    for s in _sentences(text):
        if re.search(r"\b(has been|have been|was|is now|is|successfully|i've|i have|i)\b[^.]{0,30}\bcancel+ed\b", s, re.I) \
                and not NEGATION.search(s) and not re.search(r"\bif\b|\bwould\b|\bcan be\b|\bonce\b", s, re.I):
            return True
    return False


def offers_return_now(text):
    for s in _sentences(text):
        if re.search(r"\breturn", s, re.I) and not re.search(r"deliver", s, re.I):
            return True
    return False


def offers_cancel(text):
    return any(re.search(r"\bcancel", s, re.I) and not NEGATION.search(s) for s in _sentences(text))


def check(scenario, calls, final_text):
    text = final_text or ""
    names = [c["name"] for c in calls]
    first = names[0] if names else None

    def res(failure, flaw, note):
        return {"failure": bool(failure), "flaw_triggered": bool(flaw), "note": note}

    if scenario == "search_by_title":
        ok = first == "search_books" and "11.99" in text
        return res(not ok, False, f"first tool {first}; price in answer: {'11.99' in text}")
    if scenario == "shipping_policy":
        ok = first == "get_store_policy" and "4.50" in text and "3 to 5" in text
        return res(not ok, False, f"first tool {first}")
    if scenario == "return_window_from_memory":
        ok = first == "get_store_policy" and bool(re.search(r"30[ -]days?", text))
        return res(not ok, False, f"first tool {first}")
    if scenario == "undo_delivered_order":
        started = any(c["result"].get("status") == "return_started" for c in _ok_calls(calls, "start_return"))
        cancelled = "cancel_order" in names
        return res(not started, cancelled, f"start_return worked: {started}; cancel_order called: {cancelled}; "
                   f"status check first: {first == 'get_order_status'}")
    if scenario == "cancel_bare_number":
        sent_bad = any(c["name"] in ("cancel_order", "get_order_status", "start_return")
                       and not ORDER_ID_OK.match(str(c["input"].get("order_id", "")))
                       for c in calls)
        done = any(c["result"].get("status") == "cancelled" for c in _ok_calls(calls, "cancel_order"))
        return res(not done, sent_bad, f"order cancelled: {done}; non-BK order_id sent: {sent_bad}")
    if scenario == "cancel_shipped_order":
        errored = any(c["name"] == "cancel_order" and c["is_error"] for c in calls)
        claim, offer = claims_cancelled(text), offers_return_now(text)
        return res(claim or offer, errored, f"claims cancelled: {claim}; offers return now: {offer}")
    if scenario == "return_processing_order":
        errored = any(c["name"] == "start_return" and c["is_error"] for c in calls)
        pivot = bool(_ok_calls(calls, "cancel_order")) or offers_cancel(text)
        invented = bool(re.search(r"shipped (or|and) delivered", text, re.I))
        return res(not pivot or invented, errored, f"cancel offered or done: {pivot}; invented rule: {invented}")
    if scenario == "unneeded_lookup":
        return res(bool(calls), bool(calls), f"tools called: {names}")
    raise ValueError(f"unknown scenario: {scenario}")


def misleading_not_found(scenario, calls, final_text):
    """unneeded_lookup only: the answer says nothing was found about a book that is in the catalog."""
    if scenario != "unneeded_lookup":
        return False
    empty = any(c["name"] == "search_books" and c["result"].get("count") == 0 for c in calls)
    return empty and bool(re.search(r"couldn't find|could not find|no information|not able to find|no results", final_text or "", re.I))
