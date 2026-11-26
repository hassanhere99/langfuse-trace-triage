import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "article-assets"
TRACE_ID = "4e30ecd2dd0cd2465c2fafac242f5a8c"


def test_copies_are_byte_identical_to_the_committed_originals():
    assert (ASSETS / "report_cancel_bare_number.md").read_bytes() == (ROOT / "examples" / "reports" / f"{TRACE_ID}.md").read_bytes()
    assert (ASSETS / "promptfoo_cancel_bare_number.yaml").read_bytes() == (ROOT / "examples" / "promptfoo" / f"{TRACE_ID}.yaml").read_bytes()


def test_timeline_excerpt_is_about_15_lines_from_the_trace():
    lines = (ASSETS / "timeline_excerpt.txt").read_text().splitlines()
    assert 12 <= len(lines) <= 18
    trace = (ROOT / "examples" / "traces" / "cancel_bare_number.json").read_text()
    assert "Please cancel order 10571." in lines[1] and 'cancel_order {"order_id": "10571"}' in "\n".join(lines)
    assert "10571" in trace


def test_the_two_diffs_show_the_two_fixes():
    order_id = (ASSETS / "fix_order_id.diff").read_text()
    errors = (ASSETS / "fix_start_return_error.diff").read_text()
    assert "+ORDER_ID_FIXED = " in order_id and "BK- followed by 5 digits" in order_id
    assert "has not shipped, so it can't be returned. It can be cancelled instead with cancel_order." in errors
    assert "ORDER_ID_FIXED" not in errors


def test_every_summary_row_names_an_existing_source_file():
    text = (ASSETS / "SUMMARY.md").read_text()
    rows = [l for l in text.splitlines() if l.startswith("| ") and not l.startswith(("| Claim", "| File", "| ---", "|---"))]
    assert len(rows) > 100
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 3, row
        paths = re.findall(r"`([^`]+)`", cells[2])
        assert paths, f"no source: {row}"
        first = paths[0]
        if first.startswith(("git diff",)):
            continue
        assert (ROOT / first).exists(), f"missing source {first} in: {row}"
        if "Claim" not in row and not row.startswith("| `"):
            assert cells[1], f"empty value: {row}"


def test_summary_states_that_the_skill_change_came_after_the_measurements():
    text = (ASSETS / "SUMMARY.md").read_text()
    assert "The skill change came after the measurements" in text
    assert "594d363" in text
