import json
from pathlib import Path

import pytest

import failure_checks as fc
import summarize_trace as st

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "examples" / "traces"

# What the committed (flawed, temperature 0) baseline runs did, by hand from the traces.
BASELINE = {
    "search_by_title": (False, False),
    "shipping_policy": (False, False),
    "return_window_from_memory": (False, False),
    "undo_delivered_order": (False, False),   # start_return on a delivered order worked
    "cancel_bare_number": (True, True),
    "cancel_shipped_order": (True, True),
    "return_processing_order": (True, True),
    "unneeded_lookup": (True, True),
}


def baseline(scenario):
    summary = st.summarize(json.loads((TRACES / f"{scenario}.json").read_text()))
    return fc.calls_from_summary(summary), summary["final_answer"]


@pytest.mark.parametrize("scenario", sorted(BASELINE))
def test_checks_agree_with_the_committed_baseline_traces(scenario):
    calls, text = baseline(scenario)
    r = fc.check(scenario, calls, text)
    assert (r["failure"], r["flaw_triggered"]) == BASELINE[scenario], r


def test_unneeded_lookup_baseline_has_the_misleading_not_found_answer():
    calls, text = baseline("unneeded_lookup")
    assert fc.misleading_not_found("unneeded_lookup", calls, text)
    assert not fc.misleading_not_found("search_by_title", calls, text)


def call(name, args, result, err=False):
    return {"name": name, "input": args, "result": result, "is_error": err}


def test_bare_number_retried_with_prefix_is_a_recovery():
    calls = [call("cancel_order", {"order_id": "10571"}, {"error": "x"}, True),
             call("cancel_order", {"order_id": "BK-10571"}, {"status": "cancelled"})]
    r = fc.check("cancel_bare_number", calls, "Done.")
    assert r == {"failure": False, "flaw_triggered": True, "note": r["note"]}


def test_bare_number_never_cancelled_fails():
    calls = [call("cancel_order", {"order_id": "10571"}, {"error": "x"}, True)]
    assert fc.check("cancel_bare_number", calls, "I could not find it")["failure"]


def test_prefixed_order_id_first_time_is_not_flaw_triggered():
    calls = [call("cancel_order", {"order_id": "BK-10571"}, {"status": "cancelled"})]
    r = fc.check("cancel_bare_number", calls, "Cancelled.")
    assert not r["failure"] and not r["flaw_triggered"]


@pytest.mark.parametrize("text,expected_fail", [
    ("Sorry, BK-10388 has shipped so it can't be cancelled. Once it is delivered you can start a return.", False),
    ("I'm sorry, it has shipped and can't be cancelled. A return can be started after delivery.", False),
    ("It can't be cancelled. If you would like to return the book, I can send a return label.", True),
    ("Your order has been cancelled.", True),
    ("I have successfully cancelled order BK-10388.", True),
    ("It cannot be cancelled because it has shipped.", False),
])
def test_cancel_shipped_text_rules(text, expected_fail):
    calls = [call("cancel_order", {"order_id": "BK-10388"}, {"error": "shipped"}, True)]
    assert fc.check("cancel_shipped_order", calls, text)["failure"] is expected_fail


@pytest.mark.parametrize("text,expected_fail", [
    ("That order has not shipped, so it can't be returned. I can cancel it instead if you like.", False),
    ("Returns are only possible for orders that are shipped or delivered. Contact support.", True),
    ("Sorry, please contact customer support about a refund.", True),
])
def test_return_processing_text_rules(text, expected_fail):
    calls = [call("start_return", {"order_id": "BK-10571"}, {"error": "processing"}, True)]
    assert fc.check("return_processing_order", calls, text)["failure"] is expected_fail


def test_return_processing_cancel_call_counts_as_pivot():
    calls = [call("start_return", {"order_id": "BK-10571"}, {"error": "x"}, True),
             call("cancel_order", {"order_id": "BK-10571"}, {"status": "cancelled"})]
    assert not fc.check("return_processing_order", calls, "Done.")["failure"]


def test_undo_delivered_cancel_then_return_is_flaw_triggered_but_not_a_failure():
    calls = [call("cancel_order", {"order_id": "BK-10234"}, {"error": "x"}, True),
             call("start_return", {"order_id": "BK-10234"}, {"status": "return_started"})]
    r = fc.check("undo_delivered_order", calls, "Return started.")
    assert (r["failure"], r["flaw_triggered"]) == (False, True)


def test_unneeded_lookup_no_tool_is_clean():
    assert fc.check("unneeded_lookup", [], "It is suitable for teens.") == {
        "failure": False, "flaw_triggered": False, "note": "tools called: []"}


def test_controls_need_the_key_fact():
    assert fc.check("search_by_title", [call("search_books", {}, {})], "We have it for $11.99.")["failure"] is False
    assert fc.check("search_by_title", [call("search_books", {}, {})], "We have it.")["failure"] is True
    assert fc.check("return_window_from_memory", [], "30 days.")["failure"] is True


def test_unknown_scenario_raises():
    with pytest.raises(ValueError):
        fc.check("nope", [], "")
