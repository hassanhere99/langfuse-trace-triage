import json
from pathlib import Path

import score_new_reports as sn
import score_reports as sr

ROOT = Path(__file__).resolve().parent.parent
GT = sr.load_ground_truth(ROOT / "experiments" / "ground_truth.yaml")
TRACE = {"observations": [{"input": {"order_id": "10571"}, "output": {"error": "Invalid order_id: \"10571\""}}],
         "output": "I apologize, but I couldn't locate order 10571 in our system."}


def test_quotes_extracts_blockquote_lines_and_strips_labels():
    report = ("## Findings\n\n### 1. x (confidence: high)\n\nEvidence:\n\n> User: `Please cancel order 10571.`\n>\n"
              "> Tool result: `{\"error\": \"Invalid order_id\"}`\n\n## Suggested fix\n\n> not evidence\n")
    assert sn.quotes(report) == ["`Please cancel order 10571.`", '`{"error": "Invalid order_id"}`']


def test_verify_quotes_accepts_real_and_flags_invented_quotes():
    ok = "## Findings\n\n> Tool result: `{\"error\": \"Invalid order_id: \\\"10571\\\"\"}`\n> Final answer: `I apologize, but I couldn't locate order 10571 in our system.`\n"
    assert sn.verify_quotes(ok, TRACE) == (2, [])
    bad = ok + "> Final answer: `The order has been cancelled for you.`\n"
    checked, missing = sn.verify_quotes(bad, TRACE)
    assert checked == 3 and len(missing) == 1 and "cancelled" in missing[0]


def test_verify_quotes_handles_truncation_marks():
    text = "## Findings\n\n> Final answer (start): `I apologize, but I couldn't locate ... in our system.`\n"
    assert sn.verify_quotes(text, TRACE)[1] == []


def test_verify_quotes_on_a_committed_report_and_its_trace():
    report = (ROOT / "examples" / "reports" / "4e30ecd2dd0cd2465c2fafac242f5a8c.md").read_text()
    trace = json.loads((ROOT / "examples" / "traces" / "cancel_bare_number.json").read_text())
    checked, missing = sn.verify_quotes(report, trace)
    assert checked >= 4 and missing == []


def test_the_dune_report_quotes_are_real_even_though_one_inference_is_wrong():
    # The automated check cannot see the wrong "store does not list Dune" inference. This documents the limit.
    report = (ROOT / "examples" / "reports" / "d16c62931b297a2bcd47834deb76a519.md").read_text()
    trace = json.loads((ROOT / "examples" / "traces" / "unneeded_lookup.json").read_text())
    checked, missing = sn.verify_quotes(report, trace)
    assert checked >= 4 and missing == []


def run(scenario="cancel_bare_number", variant="fixed", failure=True, flaw=True):
    return {"scenario": scenario, "variant": variant, "run": 1, "trace_id": "t", "failure": failure,
            "flaw_triggered": flaw, "tool_errors": 1, "tools": ["cancel_order"], "file": "x", "note": "n"}


def test_truth_for_uses_the_pre_committed_rules():
    t = sn.truth_for(run(), GT)
    assert (t["expected_failure_type"], t["expected_fix_location"], t["ambiguous"]) == ("model_error", "none", True)
    t = sn.truth_for(run(variant="flawed"), GT)
    assert (t["expected_failure_type"], t["expected_fix_location"]) == ("wrong_arguments", "tool_schema")
    t = sn.truth_for(run(failure=False, flaw=False), GT, quotes_ok=False)
    assert t["expected_failure_type"] == "no_failure" and t["evidence_correct"] is False


def test_score_variant_end_to_end(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps(TRACE))
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "t.md").write_text(
        "# Trace t\n\n## Findings\n\n### 1. wrong_arguments (confidence: high)\n\n> Tool result: `Invalid order_id`\n\n"
        "## Suggested fix\n\nLocation: schema of `cancel_order`\n")
    r = dict(run(variant="flawed"), file="x.json")
    rows = sn.score_variant("flawed", [r, dict(r, trace_id="missing")], rep, GT, repo_root=tmp_path)
    assert len(rows) == 1
    assert rows[0]["label_ok"] and rows[0]["location_ok"] and rows[0]["fully_correct"]
    text = sn.render_rows(rows) + sn.render_totals("flawed", rows)
    assert "Label accuracy (primary finding) | 1/1 | 1/1" in text


def test_arrow_elision_and_bracket_labels_in_quotes():
    trace = {"a": "cancel_order", "b": {"order_id": "10571"}, "c": "Invalid order_id: 10571 for this request"}
    report = ("## Findings\n\n> `cancel_order {\"order_id\": \"10571\"}  ->  Invalid order_id: 10571 for this request`\n"
              "> `[tool result] Invalid order_id: 10571 [...] this request`\n")
    assert sn.verify_quotes(report, trace) == (2, [])


def test_no_failure_found_summary_under_an_inconclusive_heading_is_read_as_no_failure(tmp_path):
    text = ("# Trace t\n\n- Summary: No failure found. The agent did what was asked.\n\n## Findings\n\n"
            "### 1. inconclusive (confidence: high that the run is correct)\n\n> User: `Please cancel order 10571.`\n\n"
            "## Suggested fix\n\nNone.\n")
    parsed = sr.parse_report(text)
    assert parsed["summary_no_failure"] and parsed["labels"] == ["inconclusive"]
    assert sn.read_as_no_failure(parsed)["labels"] == ["no_failure"]
    real = dict(parsed, summary_no_failure=False)
    assert sn.read_as_no_failure(real)["labels"] == ["inconclusive"]
    (tmp_path / "x.json").write_text(json.dumps({"q": "Please cancel order 10571."}))
    rep = tmp_path / "r"
    rep.mkdir()
    (rep / "t.md").write_text(text)
    r = dict(run(variant="fixed", failure=False, flaw=False), file="x.json", tools=["cancel_order"], note="n")
    strict = sn.score_variant("fixed", [r], rep, GT, repo_root=tmp_path)
    adj = sn.score_variant("fixed", [r], rep, GT, repo_root=tmp_path, adjusted=True)
    assert strict[0]["false_positive"] is True and adj[0]["false_positive"] is False


def _row(scenario, expected_label, expected_loc, locations):
    truth = {"scenario": scenario, "expected_failure_type": expected_label, "expected_fix_location": expected_loc,
             "tools_involved": ["cancel_order"], "ambiguous": False, "evidence_correct": True}
    row = sr.score_one(truth, {"labels": ["x"], "confidences": ["high"], "locations": locations, "citations": []})
    row.update(expected_location=expected_loc, run=1)
    return row


def test_fix_location_on_failed_traces_excludes_clean_ones_and_has_a_lenient_reading():
    rows = [
        _row("a", "wrong_arguments", "tool_schema", ["tool_schema", "error_message"]),   # primary right
        _row("a", "wrong_arguments", "tool_schema", ["error_message", "tool_schema"]),   # right one only named second
        _row("a", "wrong_arguments", "tool_schema", ["system_prompt"]),                   # wrong
        _row("b", "tool_error_mishandled", "error_message", ["error_message"]),
        _row("clean", "no_failure", "none", ["none"]),                                    # must not count
        _row("clean", "no_failure", "none", ["tool_description"]),                        # must not count
    ]
    t = sr.totals(rows)
    assert t["location_failed"] == (2, 4)
    assert t["location_failed_any"] == (3, 4)
    assert t["location"] == 3  # the all-traces figure still counts the clean one that got `none`
    assert sn.location_by_scenario(rows) == [("a", 3, 1, 2), ("b", 1, 1, 1)]
    table = sn.render_location_by_scenario(rows)
    assert "| a | 3 | `tool_schema` | 1/3 | 2/3 |" in table
    assert "| **All failed traces** | **4** | | **2/4** | **3/4** |" in table
    assert "clean" not in table


def test_totals_table_shows_the_two_failed_trace_rows():
    rows = [_row("a", "wrong_arguments", "tool_schema", ["tool_schema"])]
    text = sn.render_totals("x", rows)
    assert "Fix-location accuracy on traces that failed, primary location | 1/1 | 1/1" in text
    assert "Fix-location accuracy on traces that failed, right location named anywhere | 1/1 | 1/1" in text


def test_committed_reports_score_still_has_the_location_any_key():
    truth = sr.load_ground_truth(ROOT / "experiments" / "ground_truth.yaml")
    rows = [sr.score_one(t, sr.parse_report((ROOT / "examples" / "reports" / f"{t['trace_id']}.md").read_text())) for t in truth]
    assert sr.totals(rows)["location_failed"] == (4, 4)
