"""The skill's text after step 6: the tie-break rule and the explicit fix_location field."""
import re
from pathlib import Path

import score_reports as sr

SKILL = Path(__file__).resolve().parent.parent / "skills" / "langfuse-trace-triage"
TIE_BREAK = ("When a symptom (wrong tool, wrong arguments…) and a root cause (overlapping descriptions, missing format…) "
             "both fit, label the root cause, and put the symptom in the evidence.")


def test_tie_break_rule_is_in_skill_md_and_the_failure_list():
    assert TIE_BREAK in (SKILL / "SKILL.md").read_text()
    assert TIE_BREAK in (SKILL / "reference" / "failure-types.md").read_text()


def test_report_template_has_a_fix_location_field_with_the_five_values():
    text = (SKILL / "reference" / "output-format.md").read_text()
    template = text[text.index("## Report template"):text.index("Notes:")]
    assert re.search(r"^fix_location: <.*tool_description.*tool_schema.*error_message.*system_prompt.*none", template, re.M)
    notes = text[text.index("Notes:"):text.rindex("## promptfoo test case")]
    for value in sr.LOCATIONS:
        assert f"`{value}`" in notes


def test_skill_md_asks_for_the_field():
    assert "`fix_location`" in (SKILL / "SKILL.md").read_text()


def test_the_scorer_reads_the_explicit_field_before_the_prose_line():
    report = ("## Findings\n\n### 1. wrong_arguments (confidence: high)\n\n## Suggested fix\n\n"
              "fix_location: tool_schema, error_message\nLocation: system prompt of `x`\n")
    assert sr.parse_report(report)["locations"] == ["tool_schema", "error_message"]


def test_a_clean_report_with_the_field_is_none():
    report = "- Summary: No failure found.\n\n## Findings\n\nNone.\n\n## Suggested fix\n\nfix_location: none\n\nNone.\n"
    assert sr.parse_report(report)["locations"] == ["none"]


def test_committed_reports_still_parse_the_same_way():
    # They predate the field, so the prose Location: line is used.
    root = Path(__file__).resolve().parent.parent
    p = sr.parse_report((root / "examples" / "reports" / "4e30ecd2dd0cd2465c2fafac242f5a8c.md").read_text())
    assert p["locations"] == ["tool_schema", "error_message"]


# --- skill v2: no_failure is a verdict, inconclusive is for a suspected failure the trace cannot settle -------

SKILL_MD = (SKILL / "SKILL.md").read_text()
FAILURE_TYPES = (SKILL / "reference" / "failure-types.md").read_text()
OUTPUT_FORMAT = (SKILL / "reference" / "output-format.md").read_text()


def _fenced(text, heading):
    """The ````markdown block that follows a heading."""
    after = text[text.index(heading):]
    start = after.index("````markdown") + len("````markdown")
    return after[start:after.index("````", start)].strip("\n")


def test_skill_md_states_both_rules():
    assert "A run with nothing wrong is not `inconclusive`" in SKILL_MD
    assert "verdict `no_failure`: no Findings section, and `fix_location: none`" in SKILL_MD
    assert "name the data that would settle it" in SKILL_MD
    assert "never to say that a clean run is clean" in SKILL_MD


def test_failure_types_defines_inconclusive_as_a_suspected_failure_and_no_failure_as_a_verdict():
    inconclusive = FAILURE_TYPES[FAILURE_TYPES.index("## inconclusive"):FAILURE_TYPES.index("## no_failure")]
    assert "Something looks wrong, and the trace cannot show why or whether" in inconclusive
    assert "It is not for a run where nothing is wrong: that is `no_failure`" in inconclusive
    assert "must name the data that would settle it" in inconclusive
    no_failure = FAILURE_TYPES[FAILURE_TYPES.index("## no_failure"):FAILURE_TYPES.index("## Confidence")]
    assert "no Findings section" in no_failure and "`fix_location: none`" in no_failure


def test_output_format_has_a_no_failure_template_without_findings():
    template = _fenced(OUTPUT_FORMAT, "### Report when nothing is wrong")
    assert "- Verdict: no_failure" in template
    assert "fix_location: none" in template
    assert "## Findings" not in template and "### 1." not in template and "inconclusive" not in template


def test_output_format_requires_naming_the_data_for_inconclusive():
    block = _fenced(OUTPUT_FORMAT, "### Report when the trace cannot settle a suspected failure")
    assert "### 1. inconclusive" in block and "Data that would settle it:" in block
    assert "`inconclusive` is never a way to say that a run is correct" in OUTPUT_FORMAT


def test_the_parser_reads_a_report_written_from_the_no_failure_template():
    template = _fenced(OUTPUT_FORMAT, "### Report when nothing is wrong")
    report = (template.replace("<trace_id>", "t1").replace("<trace timestamp>", "2026-11-27T00:00:00Z")
              .replace('<score name, value, comment; or "none">', "none")
              .replace("<one line: what the agent did and why it was right>", "The agent called the right tool.")
              .replace("<one line saying what was checked, for example that every figure in the answer comes from a tool result>",
                       "Every figure in the answer comes from the tool result."))
    parsed = sr.parse_report(report)
    assert parsed["labels"] == ["no_failure"] and parsed["confidences"] == []
    assert parsed["locations"] == ["none"]
    assert parsed["summary_no_failure"] is True
    truth = {"scenario": "shipping_policy", "expected_failure_type": "no_failure", "expected_fix_location": "none",
             "tools_involved": ["get_store_policy"], "ambiguous": False, "evidence_correct": True}
    row = sr.score_one(truth, parsed)
    assert row["label_ok"] and row["location_ok"] and not row["false_positive"]


def test_the_old_misuse_still_parses_as_inconclusive_so_v1_numbers_do_not_change():
    v1_style = ("- Summary: No failure found. fine.\n\n## Findings\n\n### 1. inconclusive (confidence: high that the run is correct)\n\n"
                "## Suggested fix\n\nfix_location: none\n")
    parsed = sr.parse_report(v1_style)
    assert parsed["labels"] == ["inconclusive"] and parsed["summary_no_failure"] is True
