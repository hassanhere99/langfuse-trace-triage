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
