"""Score the skill's triage reports against a hand-written ground truth.

    python experiments/score_reports.py                      # writes experiments/results_before.md
    python experiments/score_reports.py --reports DIR --out FILE

It reads experiments/ground_truth.yaml and, for each scenario, the report named
<trace_id>.md in the reports directory (default examples/reports). It does not modify the
reports. Nothing here calls a model or the network.

What it extracts from a report
    labels / confidences  every "### N. <failure_type> (confidence: ...)" heading, in order.
                          The first one is the "primary" label. A report with no findings
                          heading is read as "no failure found".
    fix location          the "Location:" line under "## Suggested fix", mapped to
                          tool_description | tool_schema | error_message | system_prompt.
                          "server behaviour" is mapped to error_message. A report with no
                          Location line (or "None") is read as "none". The first location
                          named is the primary one.

"Label correct" means the primary label equals the ground truth. "Fully correct" also needs
the report to state no false fact (evidence_correct in the ground truth). "Evidence in bounds"
is detected from the report text: a report that cites demo-agent/ code or other files in
examples/traces/ used evidence from outside the trace it was triaging.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FAILURE_TYPES = {
    "wrong_tool", "wrong_arguments", "missing_tool_call", "unnecessary_tool_call",
    "description_overlap", "tool_error_mishandled", "leaked_internals", "prompt_issue",
    "model_error", "inconclusive",
}
LOCATIONS = ("tool_description", "tool_schema", "error_message", "system_prompt", "none")

_FINDING_RE = re.compile(r"^###\s+\d+\.\s+([a-z_]+)\s*\(confidence:\s*(high|medium|low)", re.M | re.I)
_SUMMARY_RE = re.compile(r"^-\s*Summary:\s*(.+)$", re.M)
_LOCATION_RE = re.compile(r"^(?:Location|fix_location):\s*(.+)$", re.M | re.I)
_FIX_LOCATION_FIELD_RE = re.compile(r"^fix_location:\s*(.+)$", re.M | re.I)
_FIX_SECTION_RE = re.compile(r"^##\s+Suggested fix\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)

# (regex on the Location text with parentheses removed, normalised value)
_LOCATION_PATTERNS = (
    (re.compile(r"system prompt"), "system_prompt"),
    (re.compile(r"server behaviou?r|error message"), "error_message"),
    (re.compile(r"schema"), "tool_schema"),
    (re.compile(r"tool description"), "tool_description"),
)


def parse_locations(text):
    """Map free text such as 'schema (...) of `x`, plus the error message ...' to an ordered list."""
    if re.match(r"\s*none\b", text, re.I):
        return ["none"]
    # The explicit field form already uses the normalised values.
    tokens = [t for t in re.split(r"[,\s|]+", text.strip().lower()) if t]
    if tokens and all(t in LOCATIONS for t in tokens):
        return list(dict.fromkeys(tokens))
    plain = re.sub(r"\([^)]*\)", " ", text.lower())  # parenthetical notes often name other things
    hits = []
    for pattern, value in _LOCATION_PATTERNS:
        m = pattern.search(plain)
        if m:
            hits.append((m.start(), value))
    hits.sort()
    out = []
    for _, value in hits:
        if value not in out:
            out.append(value)
    return out or ["unrecognised"]


_CITATION_PATTERNS = (
    (re.compile(r"demo-agent/tools\.py"), "demo-agent/tools.py"),
    (re.compile(r"examples/traces/"), "other trace files (examples/traces/)"),
)


def out_of_bounds_citations(text):
    """Sources outside the triaged trace that the report cites as evidence."""
    return [name for pattern, name in _CITATION_PATTERNS if pattern.search(text)]


def parse_report(text):
    """Return {"labels", "confidences", "locations", "citations"} for one report.

    summary_no_failure is True when the report's Summary line starts with "No failure". The skill
    sometimes files such a verdict under an `inconclusive` finding heading; the scorers can then show
    the label both as written and read as no_failure.
    """
    findings = [(m.group(1).lower(), m.group(2).lower()) for m in _FINDING_RE.finditer(text)]
    section = _FIX_SECTION_RE.search(text)
    locations = ["none"]
    if section:
        # The explicit field (added to the skill after the committed reports were made) wins over the prose line.
        loc = _FIX_LOCATION_FIELD_RE.search(section.group(1)) or _LOCATION_RE.search(section.group(1))
        if loc:
            locations = parse_locations(loc.group(1))
    summary = _SUMMARY_RE.search(text)
    return {
        "summary_no_failure": bool(summary and re.match(r"no failure", summary.group(1).strip(), re.I)),
        "labels": [f[0] for f in findings] or ["no_failure"],
        "confidences": [f[1] for f in findings],
        "locations": locations,
        "citations": out_of_bounds_citations(text),
    }


def load_ground_truth(path):
    data = yaml.safe_load(Path(path).read_text())
    return data["scenarios"]


_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def worst_wrong_findings(labels, confidences, expected):
    """The wrong findings (label != expected) that have the highest confidence."""
    wrong = [(l, c) for l, c in zip(labels, confidences) if l != expected]
    if not wrong:
        return []
    top = max(_CONF_RANK[c] for _, c in wrong)
    return [(l, c) for l, c in wrong if _CONF_RANK[c] == top]


def score_one(truth, parsed):
    labels, locations = parsed["labels"], parsed["locations"]
    expected_label, expected_loc = truth["expected_failure_type"], truth["expected_fix_location"]
    label_ok = labels[0] == expected_label
    clean = expected_label == "no_failure"
    return {
        "scenario": truth["scenario"],
        "ambiguous": bool(truth.get("ambiguous")),
        "labels": labels,
        "confidences": parsed["confidences"],
        "locations": locations,
        "label_ok": label_ok,
        "evidence_ok": bool(truth.get("evidence_correct", True)),
        "fully_correct": label_ok and bool(truth.get("evidence_correct", True)),
        "citations": parsed.get("citations", []),
        "location_ok": locations[0] == expected_loc,
        "location_any": expected_loc in locations,
        "clean": clean,
        "false_positive": clean and labels != ["no_failure"],
        "worst_wrong": worst_wrong_findings(labels, parsed["confidences"], expected_label) if clean else [],
        "system_prompt_suggested": "system_prompt" in locations,
        "single_tool": len(truth.get("tools_involved", [])) == 1,
    }


def totals(rows):
    n = len(rows)
    firm = [r for r in rows if not r["ambiguous"]]
    clean = [r for r in rows if r["clean"]]
    failing = [r for r in rows if not r["clean"]]
    single = [r for r in failing if r["single_tool"]]
    return {
        "n": n,
        "label": sum(r["label_ok"] for r in rows),
        "fully_correct": sum(r["fully_correct"] for r in rows),
        "evidence_in_bounds": sum(not r["citations"] for r in rows),
        "location": sum(r["location_ok"] for r in rows),
        # fix-location accuracy on traces that actually failed: the expected-clean traces are left out
        "location_failed": (sum(r["location_ok"] for r in failing), len(failing)),
        "location_failed_any": (sum(r["location_any"] for r in failing), len(failing)),
        "label_firm": (sum(r["label_ok"] for r in firm), len(firm)),
        "location_firm": (sum(r["location_ok"] for r in firm), len(firm)),
        "false_pos": (sum(r["false_positive"] for r in clean), len(clean)),
        "sys_prompt_single": (sum(r["system_prompt_suggested"] for r in single), len(single)),
        "sys_prompt_any": sum(r["system_prompt_suggested"] for r in rows),
    }


def _yn(ok, expected):
    return f"{'yes' if ok else 'no'} (expected `{expected}`)"


def _evidence_cell(r, truth):
    if r["evidence_ok"]:
        return "yes"
    reason = truth.get("evidence_note", "").split(". ")[0].rstrip(".")
    return f"no: {reason} → not fully correct"


def _bounds_cell(r):
    return "yes" if not r["citations"] else "no: cites " + ", ".join(r["citations"])


def render(truth_rows, rows, reports_dir):
    t = totals(rows)
    n = t["n"]
    out = []
    out.append("# Results before: the committed reports scored against the ground truth\n")
    out.append(
        "Generated by `experiments/score_reports.py` from `experiments/ground_truth.yaml` and the "
        f"reports in `{reports_dir}`. No new runs. The reports are the baseline and were not changed.\n"
    )
    out.append(
        "Rows marked † have an ambiguous ground-truth label (reason in `ground_truth.yaml`). "
        "\"Skill label\" lists every finding in the report, primary first; \"Label correct?\" and "
        "\"Location correct?\" are judged on the primary (first) one. Confidence is listed per "
        "finding in the same order. A report is fully correct only if the label is right and none of "
        "its stated facts is false (\"Evidence correct?\"). \"Evidence in bounds?\" asks whether the "
        "report used only the trace it was triaging.\n"
    )
    out.append("| Scenario | Planted flaw | Agent behaviour | Skill label | Confidence | Label correct? | Evidence correct? | Evidence in bounds? | Fix location | Location correct? |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for tr, r in zip(truth_rows, rows):
        mark = " †" if r["ambiguous"] else ""
        labels = ", ".join(f"`{x}`" for x in r["labels"])
        conf = " / ".join(r["confidences"]) or "n/a"
        locs = ", ".join(f"`{x}`" for x in r["locations"])
        out.append(
            f"| {r['scenario']}{mark} | {tr['planted_flaw']} | {tr['behaviour_short']} | {labels} | {conf} | "
            f"{_yn(r['label_ok'], tr['expected_failure_type'])} | {_evidence_cell(r, tr)} | {_bounds_cell(r)} | "
            f"{locs} | {_yn(r['location_ok'], tr['expected_fix_location'])} |"
        )
    out.append("")
    out.append("## Totals\n")
    out.append("| Measure | Result |")
    out.append("|---|---|")
    out.append(f"| Label accuracy (primary finding) | {t['label']}/{n} |")
    out.append(f"| Fully correct (label right and no false fact) | {t['fully_correct']}/{n} |")
    out.append(f"| Fix-location accuracy (primary location) | {t['location']}/{n} |")
    out.append(f"| Label accuracy without ambiguous rows | {t['label_firm'][0]}/{t['label_firm'][1]} |")
    out.append(f"| Fix-location accuracy without ambiguous rows | {t['location_firm'][0]}/{t['location_firm'][1]} |")
    out.append(f"| Reports whose evidence stayed inside the trace | {t['evidence_in_bounds']}/{n} |")
    fp_rows = [r for r in rows if r["false_positive"]]
    detail = "; ".join(
        f"`{r['scenario']}`: " + ", ".join(f"`{l}` ({c})" for l, c in r["worst_wrong"]) for r in fp_rows
    )
    out.append(
        f"| False positives (a failure reported where the agent behaved correctly) | "
        f"{t['false_pos'][0]}/{t['false_pos'][1]} clean-behaviour traces"
        + (f". Highest-confidence wrong finding: {detail}" if detail else "")
        + " |"
    )
    out.append(f"| Reports that suggested a system-prompt edit for a failure involving only one tool | {t['sys_prompt_single'][0]} of {t['sys_prompt_single'][1]} single-tool failures |")
    out.append(f"| Reports that suggested a system-prompt edit at all | {t['sys_prompt_any']} of {n} |")
    out.append("")
    out.append("## Notes\n")
    out.append(
        "- Clean-behaviour traces are the four with ground truth `no_failure`: `search_by_title`, `shipping_policy`, "
        "`return_window_from_memory` and `undo_delivered_order` (ambiguous: the outcome was right, but the status check "
        "was skipped and `reason` was filled with \"None\").\n"
        "- Ground truth: planted flaws were defined in the scenario design before any report existed. Only the "
        "\"what the agent did\" column and the expected labels for the scenarios that diverged from their design were "
        "written after reading the reports. Treat the ambiguous rows as open.\n"
        "- A \"fix location\" is read from the report's `Location:` line. Reports name several locations in one line, so the "
        "first one named counts as primary. `server behaviour` is mapped to `error_message`. The reports have no "
        "explicit `fix_location` field yet (that is step 6), so this is a text parse and can be wrong for a phrasing it has not seen.\n"
        "- The system-prompt count looks only at the `Location:` line. Reports that mention the system prompt only to say "
        "the fix does not belong there are not counted. Single-tool failures are the non-clean scenarios whose "
        "`tools_involved` has one entry.\n"
        "- **The reports were made by an earlier version of the skill.** The rule \"use only the trace being triaged\" "
        "was added in commit `9feb2e8`, after the reports were committed (`3ee0a5a`, from the skill as of `995c40e`). "
        "Three reports cite material outside their trace: `cancel_shipped_order` and `return_processing_order` cite "
        "`demo-agent/tools.py`, and `cancel_bare_number` infers the `BK-` format from other trace files. The current skill "
        "would not be allowed to do that.\n"
        "- Evidence correctness is checked by hand against the traces and `demo-agent/tools.py` (see `evidence_note` in the "
        "ground truth). `unneeded_lookup` has a false claim, see `experiments/discovered_bugs.md`.\n"
    )
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ground-truth", default=str(ROOT / "experiments" / "ground_truth.yaml"))
    ap.add_argument("--reports", default=str(ROOT / "examples" / "reports"))
    ap.add_argument("--out", default=str(ROOT / "experiments" / "results_before.md"))
    args = ap.parse_args(argv)

    truth_rows = load_ground_truth(args.ground_truth)
    reports_dir = Path(args.reports)
    rows = []
    for tr in truth_rows:
        path = reports_dir / f"{tr['trace_id']}.md"
        if not path.is_file():
            sys.stderr.write(f"missing report: {path}\n")
            return 1
        rows.append(score_one(tr, parse_report(path.read_text())))
    try:
        shown = str(reports_dir.resolve().relative_to(ROOT))
    except ValueError:
        shown = str(reports_dir)
    Path(args.out).write_text(render(truth_rows, rows, shown))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
