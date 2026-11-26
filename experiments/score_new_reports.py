"""Score the skill's reports on the NEW experiment traces with the same scoring as score_reports.py.

Differences from the committed-report scoring, all forced by there being ~40 traces instead of 8:
    expected label / location   from the rules in expected_labels.py (fixed before triage), not by hand
    evidence correct            automated: every quoted line in the report's Findings section must
                                appear in the trace. This catches invented quotes. It does not catch a
                                wrong inference from a true quote (the unneeded_lookup "store does not
                                list Dune" kind); those are only caught where a human read the report.
    evidence in bounds          detected from the report text, as before
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))

import expected_labels  # noqa: E402
import score_reports as sr  # noqa: E402

_FINDINGS_RE = re.compile(r"^##\s+Findings\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)
_LABEL_RE = re.compile(r"^[^:{\"`]{0,40}`?[\w.\- ]{0,40}`?:\s+")


def _norm(s):
    return re.sub(r"[\s\\`\"']", "", s)


def quotes(report_text):
    """Quoted evidence lines (blockquotes) from the Findings section, label prefixes removed."""
    m = _FINDINGS_RE.search(report_text)
    section = m.group(1) if m else ""
    out = []
    for line in section.splitlines():
        if not line.lstrip().startswith(">"):
            continue
        body = line.lstrip("> ").strip()
        body = _LABEL_RE.sub("", body, count=1) if re.match(r"^[^:{\"`]{0,40}:\s", body) or re.match(r"^`[\w.\-]+`:\s", body) else body
        if body:
            out.append(body)
    return out


def _pieces(quote):
    """Strings to look up for one quote line: each backtick span if there are any, else the whole line.
    A tool call is quoted as `name {args}` but stored as a name and a separate arguments string, so
    spans are also split before a "{", and at "->" (call -> result). Truncation marks ("...", "[...]") split a
    quote into its visible parts. A bracketed label such as "[tool result]" is ignored."""
    spans = re.findall(r"`([^`]+)`", quote) or [quote]
    out = []
    for span in spans:
        span = re.sub(r"^\[[a-z ]+\]\s*", "", span.strip())  # "[tool result] ..." style labels
        for part in re.split(r"\.\.\.|…|\[\.\.\.\]|\s*(?:->|→)\s*|\s+(?=\{)", span):
            if len(_norm(part)) >= 8:
                out.append(part)
    return out


def verify_quotes(report_text, trace):
    """(number of quote lines checked, quote lines not found in the trace)."""
    blob = _norm(json.dumps(trace, ensure_ascii=False))
    blob += _norm(json.dumps(trace, ensure_ascii=True))
    checked, missing = 0, []
    for q in quotes(report_text):
        pieces = _pieces(q)
        if not pieces:
            continue
        checked += 1
        if not all(_norm(p) in blob for p in pieces):
            missing.append(q)
    return checked, missing


def truth_for(run, ground_truth, quotes_ok=True):
    """A ground-truth-like row for one triaged run, built by the pre-committed rules."""
    base = next(t for t in ground_truth if t["scenario"] == run["scenario"])
    exp = expected_labels.expected_for(run["variant"], run["scenario"], run, base)
    return {
        "scenario": run["scenario"], "expected_failure_type": exp["label"], "expected_fix_location": exp["location"],
        "tools_involved": base["tools_involved"], "ambiguous": exp["ambiguous"], "evidence_correct": quotes_ok,
        "expected_reason": exp["reason"],
    }


def read_as_no_failure(parsed):
    """The parse with an `inconclusive` finding under a "No failure found" summary read as no_failure."""
    if parsed.get("summary_no_failure") and parsed["labels"] == ["inconclusive"]:
        return dict(parsed, labels=["no_failure"], confidences=[])
    return parsed


def score_variant(variant, runs, reports_dir, ground_truth, repo_root=ROOT, adjusted=False):
    """Rows for every triaged run of a variant that has a report.

    adjusted=True reads an `inconclusive` finding under a "No failure found" summary as no_failure."""
    rows = []
    for run in runs:
        report = Path(reports_dir) / f"{run['trace_id']}.md"
        if not report.is_file():
            continue
        text = report.read_text()
        trace = json.loads((repo_root / run["file"]).read_text())
        checked, missing = verify_quotes(text, trace)
        truth = truth_for(run, ground_truth, quotes_ok=not missing)
        parsed = sr.parse_report(text)
        row = sr.score_one(truth, read_as_no_failure(parsed) if adjusted else parsed)
        row.update(as_written=parsed["labels"], behaviour=f"{' → '.join(run['tools']) or 'no tool'}; {run['note']}", run=run["run"], trace_id=run["trace_id"], variant=variant, quotes_checked=checked,
                   quotes_missing=missing, expected=truth["expected_failure_type"],
                   expected_location=truth["expected_fix_location"], expected_reason=truth["expected_reason"])
        rows.append(row)
    return rows


def render_rows(rows):
    out = ["| Scenario | Run | What the run did | Skill label | Confidence | Expected | Label correct? | Quotes verified | In bounds? | Fix location | Location correct? |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mark = " †" if r["ambiguous"] else ""
        labels = ", ".join(f"`{x}`" for x in r["as_written"])
        if r["as_written"] != r["labels"]:
            labels += " (summary: no failure found)"
        locs = ", ".join(f"`{x}`" for x in r["locations"])
        q = f"{r['quotes_checked'] - len(r['quotes_missing'])}/{r['quotes_checked']}"
        out.append(
            f"| {r['scenario']}{mark} | {r['run']} | {r.get('behaviour', '')} | {labels} | "
            f"{' / '.join(r['confidences']) or 'n/a'} | `{r['expected']}` | {'yes' if r['label_ok'] else 'no'} | {q} | "
            f"{'yes' if not r['citations'] else 'no: ' + ', '.join(r['citations'])} | {locs} | "
            f"{'yes' if r['location_ok'] else 'no'} (expected `{r['expected_location']}`) |")
    return "\n".join(out) + "\n"


def _totals_cells(rows):
    t = sr.totals(rows)
    n = t["n"]
    fp_rows = [r for r in rows if r["false_positive"]]
    detail = "; ".join(f"`{r['scenario']}` run {r['run']}: " + ", ".join(f"`{l}` ({c})" for l, c in r["worst_wrong"]) for r in fp_rows)
    firm_clean = [r for r in rows if r["clean"] and not r["ambiguous"]]
    firm_fp = sum(r["false_positive"] for r in firm_clean)
    return t, n, detail, firm_fp, len(firm_clean)


def render_totals(label, rows, adjusted_rows=None):
    """Totals table. With adjusted_rows, a second column reads "No failure found" summaries as no_failure."""
    adjusted_rows = adjusted_rows if adjusted_rows is not None else rows
    cols = [_totals_cells(rows), _totals_cells(adjusted_rows)]
    head = f"| {label} | As written | \"No failure found\" summary read as `no_failure` |"

    def row(name, fn):
        return f"| {name} | " + " | ".join(fn(*c) for c in cols) + " |"

    lines = [
        head, "|---|---|---|",
        row("Traces triaged", lambda t, n, d, a, b: str(n)),
        row("Label accuracy (primary finding)", lambda t, n, d, a, b: f"{t['label']}/{n}"),
        row("Fully correct (label right, every quote found in the trace)", lambda t, n, d, a, b: f"{t['fully_correct']}/{n}"),
        row("Fix-location accuracy (primary location)", lambda t, n, d, a, b: f"{t['location']}/{n}"),
        row("Label accuracy without ambiguous rows", lambda t, n, d, a, b: f"{t['label_firm'][0]}/{t['label_firm'][1]}"),
        row("Fix-location accuracy without ambiguous rows", lambda t, n, d, a, b: f"{t['location_firm'][0]}/{t['location_firm'][1]}"),
        row("Reports whose evidence stayed inside the trace", lambda t, n, d, a, b: f"{t['evidence_in_bounds']}/{n}"),
        row("False positives, all expected-clean traces", lambda t, n, d, a, b: f"{t['false_pos'][0]}/{t['false_pos'][1]}" + (f". Highest-confidence wrong findings: {d}" if d else "")),
        row("False positives, unambiguous clean traces only", lambda t, n, d, a, b: f"{a}/{b}"),
        row("System-prompt edit suggested, failures involving one tool", lambda t, n, d, a, b: f"{t['sys_prompt_single'][0]} of {t['sys_prompt_single'][1]}"),
        row("System-prompt edit suggested, any report", lambda t, n, d, a, b: f"{t['sys_prompt_any']} of {n}"),
    ]
    return "\n".join(lines) + "\n"
