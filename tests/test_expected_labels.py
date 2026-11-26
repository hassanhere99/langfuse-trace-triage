import pytest

import expected_labels as el

GT = {"expected_failure_type": "wrong_arguments", "expected_fix_location": "tool_schema", "ambiguous": True}
CLEAN_GT = {"expected_failure_type": "no_failure", "expected_fix_location": "none", "ambiguous": False}
UNDO_GT = {"expected_failure_type": "no_failure", "expected_fix_location": "none", "ambiguous": True}


def run(failure=False, flaw=False, errors=0, tools=("x",)):
    return {"failure": failure, "flaw_triggered": flaw, "tool_errors": errors, "tools": list(tools)}


def test_clean_run_expects_no_failure():
    r = el.expected_for("fixed", "shipping_policy", run(), CLEAN_GT)
    assert (r["label"], r["location"], r["ambiguous"]) == ("no_failure", "none", False)


def test_clean_undo_run_inherits_the_ambiguity():
    r = el.expected_for("flawed", "undo_delivered_order", run(), UNDO_GT)
    assert (r["label"], r["ambiguous"]) == ("no_failure", True)


def test_recovered_run_is_no_failure_but_ambiguous():
    r = el.expected_for("fixed", "cancel_bare_number", run(flaw=True, errors=1), GT)
    assert (r["label"], r["location"], r["ambiguous"]) == ("no_failure", "none", True)


def test_failure_on_flawed_uses_the_ground_truth():
    r = el.expected_for("flawed", "cancel_bare_number", run(True, True, 1), GT)
    assert (r["label"], r["location"]) == ("wrong_arguments", "tool_schema")


@pytest.mark.parametrize("scenario", ["cancel_bare_number", "cancel_shipped_order", "return_processing_order"])
def test_failure_on_fixed_where_the_fix_applied_is_model_error(scenario):
    r = el.expected_for("fixed", scenario, run(True, True, 1), GT)
    assert (r["label"], r["location"], r["ambiguous"]) == ("model_error", "none", True)


def test_unneeded_lookup_failure_keeps_its_label_under_fixed_but_is_ambiguous():
    gt = {"expected_failure_type": "unnecessary_tool_call", "expected_fix_location": "tool_description", "ambiguous": True}
    r = el.expected_for("fixed", "unneeded_lookup", run(True, True, 0), gt)
    assert (r["label"], r["location"], r["ambiguous"]) == ("unnecessary_tool_call", "tool_description", True)


def test_failing_undo_run_is_description_overlap():
    r = el.expected_for("flawed", "undo_delivered_order", run(True, True, 1), UNDO_GT)
    assert (r["label"], r["location"]) == ("description_overlap", "tool_description")


def test_failing_control_without_a_tool_call_is_missing_tool_call():
    r = el.expected_for("flawed", "search_by_title", run(True, tools=()), CLEAN_GT)
    assert r["label"] == "missing_tool_call" and r["ambiguous"]
