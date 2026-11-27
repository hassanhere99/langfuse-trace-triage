"""Expected label and fix location for a NEW run, fixed by rule before any triage report exists.

The 8 committed traces have a hand-written ground truth (ground_truth.yaml). New runs need one
too, and it depends on what the run did. These rules were committed before the new traces were
triaged, so the skill's reports could not influence them. They are mechanical and coarse, which
is why most non-trivial cases are marked ambiguous.

    clean run (no failure, planted flaw not triggered)       -> no_failure / none
    planted flaw triggered but the run recovered             -> no_failure / none, ambiguous
    failure on a flawed run                                  -> the scenario's ground truth
    failure on a fixed run, where the fix addressed the flaw -> model_error / none, ambiguous
        (the schema states the format, or the error says what to do, and the model still failed)
    failure that no fix touches (overlap, unneeded_lookup)   -> the scenario's ground truth

undo_delivered_order has no failing label of its own in the ground truth (the committed run was
correct), so a failing run there is description_overlap / tool_description, ambiguous: the model
called cancel_order on a delivered order, which is what the unfixed overlap predicts.
"""
from __future__ import annotations

FIX_ADDRESSES = {"cancel_bare_number", "cancel_shipped_order", "return_processing_order"}
FIXED_VARIANTS = {"fixed", "desc_only", "errors_only"}


def expected_for(variant, scenario, run, truth):
    """Return {"label", "location", "ambiguous", "reason"} for one run record and its scenario truth."""
    failure = bool(run["failure"])
    flaw = bool(run["flaw_triggered"])
    truth_label, truth_loc = truth["expected_failure_type"], truth["expected_fix_location"]
    truth_ambiguous = bool(truth.get("ambiguous"))

    if not failure and not flaw and not run.get("tool_errors"):
        return {"label": "no_failure", "location": "none", "ambiguous": truth_label == "no_failure" and truth_ambiguous,
                "reason": "clean run" + (" (ground truth for this scenario is ambiguous)" if truth_ambiguous and truth_label == "no_failure" else "")}
    if not failure:
        return {"label": "no_failure", "location": "none", "ambiguous": True,
                "reason": "the planted flaw showed up but the run recovered or handled it"}
    if scenario == "undo_delivered_order":
        return {"label": "description_overlap", "location": "tool_description", "ambiguous": True,
                "reason": "failing undo run: the unfixed overlap is the cause"}
    if scenario in ("search_by_title", "shipping_policy", "return_window_from_memory"):
        label = "missing_tool_call" if not run.get("tools") else "model_error"
        return {"label": label, "location": "tool_description" if label == "missing_tool_call" else "none",
                "ambiguous": True, "reason": "a control scenario failed; label chosen only from whether a tool was called"}
    if variant in FIXED_VARIANTS and scenario in FIX_ADDRESSES:
        return {"label": "model_error", "location": "none", "ambiguous": True,
                "reason": "the fix addressed the flaw in this run's variant and the model still failed"}
    return {"label": truth_label, "location": truth_loc, "ambiguous": True if variant != "flawed" else truth_ambiguous,
            "reason": "failure of the kind in the scenario's ground truth"}
