import json
from pathlib import Path

import pytest

import score_reports as sr

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "experiments" / "ground_truth.yaml"
REPORTS = ROOT / "examples" / "reports"
TRACES = ROOT / "examples" / "traces"


def test_parse_locations_free_text():
    assert sr.parse_locations("schema (the `order_id` description) of `cancel_order`, plus the error message returned by the tool server.") == ["tool_schema", "error_message"]
    assert sr.parse_locations("server behaviour (error message) of `start_return`, plus the tool descriptions of `x`.") == ["error_message", "tool_description"]
    assert sr.parse_locations("tool description of `a` (both), and the schema description of `b.reason`.") == ["tool_description", "tool_schema"]
    assert sr.parse_locations("the system prompt") == ["system_prompt"]
    assert sr.parse_locations("None. Nothing to change.") == ["none"]
    assert sr.parse_locations("somewhere else entirely") == ["unrecognised"]


def test_parse_locations_explicit_field_values():
    assert sr.parse_locations("tool_schema") == ["tool_schema"]
    assert sr.parse_locations("error_message, tool_description") == ["error_message", "tool_description"]


def test_parenthetical_does_not_add_a_location():
    # "(the order_id description)" must not add tool_description.
    assert sr.parse_locations("schema (the order_id description) of x") == ["tool_schema"]


def test_parse_report_with_findings():
    text = (
        "# Trace x\n\n## Findings\n\n### 1. wrong_arguments (confidence: high, low severity)\n\n"
        "### 2. tool_error_mishandled (confidence: medium)\n\n## Suggested fix\n\n"
        "Location: schema of `cancel_order`\n\n## Limits\n"
    )
    parsed = sr.parse_report(text)
    assert parsed == {
        "labels": ["wrong_arguments", "tool_error_mishandled"],
        "confidences": ["high", "medium"],
        "locations": ["tool_schema"],
    }


def test_parse_report_without_findings_is_no_failure():
    text = "# Trace x\n\n## Findings\n\nNo failure findings.\n\n## Suggested fix\n\nNone.\n\n## Limits\n"
    assert sr.parse_report(text) == {"labels": ["no_failure"], "confidences": [], "locations": ["none"]}


def test_location_line_outside_the_fix_section_is_ignored():
    text = "## Findings\n\nLocation: system prompt\n\n## Suggested fix\n\nNone.\n"
    assert sr.parse_report(text)["locations"] == ["none"]


def test_ground_truth_is_well_formed():
    rows = sr.load_ground_truth(GROUND_TRUTH)
    assert len(rows) == 8
    assert len({r["scenario"] for r in rows}) == 8
    for r in rows:
        assert r["expected_failure_type"] in sr.FAILURE_TYPES | {"no_failure"}
        assert r["expected_fix_location"] in sr.LOCATIONS
        assert r["what_happened"].strip()
        assert r["tools_involved"]
        if r["ambiguous"]:
            assert r["ambiguous_reason"].strip()
        if r["expected_failure_type"] == "no_failure":
            assert r["expected_fix_location"] == "none"


def test_ground_truth_matches_the_committed_traces_and_reports():
    for r in sr.load_ground_truth(GROUND_TRUTH):
        trace = json.loads((TRACES / f"{r['scenario']}.json").read_text())
        trace_id = trace.get("id") or trace["trace"]["id"]
        assert trace_id == r["trace_id"]
        assert (REPORTS / f"{r['trace_id']}.md").is_file()


def test_scoring_the_committed_reports():
    truth = sr.load_ground_truth(GROUND_TRUTH)
    rows = [sr.score_one(t, sr.parse_report((REPORTS / f"{t['trace_id']}.md").read_text())) for t in truth]
    by = {r["scenario"]: r for r in rows}
    assert by["undo_delivered_order"]["labels"] == ["description_overlap", "wrong_tool", "wrong_arguments", "missing_tool_call"]
    assert by["undo_delivered_order"]["false_positive"] is True
    assert by["cancel_bare_number"]["locations"] == ["tool_schema", "error_message"]
    t = sr.totals(rows)
    assert t["n"] == 8
    assert t["label_strict"] == 7
    assert t["location_strict"] == 7
    assert t["false_pos_firm"] == (0, 3)
    assert t["false_pos_all"] == (1, 4)
    assert t["sys_prompt_single"] == (0, 2)
    assert t["sys_prompt_any"] == 0


def test_system_prompt_suggestion_is_counted_for_single_tool_failures():
    truth = {"scenario": "s", "expected_failure_type": "wrong_arguments", "expected_fix_location": "tool_schema",
             "tools_involved": ["cancel_order"], "ambiguous": False}
    row = sr.score_one(truth, {"labels": ["wrong_arguments"], "confidences": ["high"], "locations": ["system_prompt"]})
    assert row["label_ok"] and not row["location_ok"]
    assert sr.totals([row])["sys_prompt_single"] == (1, 1)


def test_main_writes_the_results_file(tmp_path):
    out = tmp_path / "results.md"
    assert sr.main(["--out", str(out)]) == 0
    text = out.read_text()
    assert "| Scenario | Planted flaw | Agent behaviour | Skill label | Confidence | Label correct? | Fix location | Location correct? |" in text
    assert "Label accuracy (primary finding) | 7/8" in text
    assert "system-prompt edit for a failure involving only one tool" in text


def test_main_fails_when_a_report_is_missing(tmp_path, capsys):
    assert sr.main(["--reports", str(tmp_path), "--out", str(tmp_path / "x.md")]) == 1
    assert "missing report" in capsys.readouterr().err
