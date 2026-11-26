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

"Correct" means the primary label (or primary location) equals the ground truth. The
lenient figures count a match anywhere in the list.
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
_LOCATION_RE = re.compile(r"^(?:Location|fix_location):\s*(.+)$", re.M | re.I)
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


def parse_report(text):
    """Return {"labels": [...], "confidences": [...], "locations": [...]} for one report."""
    findings = [(m.group(1).lower(), m.group(2).lower()) for m in _FINDING_RE.finditer(text)]
    section = _FIX_SECTION_RE.search(text)
    locations = ["none"]
    if section:
        loc = _LOCATION_RE.search(section.group(1))
        if loc:
            locations = parse_locations(loc.group(1))
    return {
        "labels": [f[0] for f in findings] or ["no_failure"],
        "confidences": [f[1] for f in findings],
        "locations": locations,
    }


def load_ground_truth(path):
    data = yaml.safe_load(Path(path).read_text())
    return data["scenarios"]


def score_one(truth, parsed):
    labels, locations = parsed["labels"], parsed["locations"]
    expected_label, expected_loc = truth["expected_failure_type"], truth["expected_fix_location"]
    label_ok = labels[0] == expected_label
    label_any = expected_label in labels
    loc_ok = locations[0] == expected_loc
    loc_any = expected_loc in locations
    clean = expected_label == "no_failure"
    return {
        "scenario": truth["scenario"],
        "ambiguous": bool(truth.get("ambiguous")),
        "labels": labels,
        "confidences": parsed["confidences"],
        "locations": locations,
        "label_ok": label_ok,
        "label_any": label_any,
        "location_ok": loc_ok,
        "location_any": loc_any,
        "clean": clean,
        "false_positive": clean and labels != ["no_failure"],
        "system_prompt_suggested": "system_prompt" in locations,
        "single_tool": len(truth.get("tools_involved", [])) == 1,
    }


def totals(rows):
    n = len(rows)
    firm = [r for r in rows if not r["ambiguous"]]
    clean = [r for r in rows if r["clean"]]
    clean_firm = [r for r in clean if not r["ambiguous"]]
    failing = [r for r in rows if not r["clean"]]
    single = [r for r in failing if r["single_tool"]]
    return {
        "n": n,
        "label_strict": sum(r["label_ok"] for r in rows),
        "label_any": sum(r["label_any"] for r in rows),
        "label_firm": (sum(r["label_ok"] for r in firm), len(firm)),
        "location_strict": sum(r["location_ok"] for r in rows),
        "location_any": sum(r["location_any"] for r in rows),
        "location_firm": (sum(r["location_ok"] for r in firm), len(firm)),
        "label_failing": (sum(r["label_ok"] for r in failing), len(failing)),
        "location_failing": (sum(r["location_ok"] for r in failing), len(failing)),
        "false_pos_firm": (sum(r["false_positive"] for r in clean_firm), len(clean_firm)),
        "false_pos_all": (sum(r["false_positive"] for r in clean), len(clean)),
        "sys_prompt_single": (sum(r["system_prompt_suggested"] for r in single), len(single)),
        "sys_prompt_any": sum(r["system_prompt_suggested"] for r in rows),
    }


def _yn(ok, any_ok, label):
    if ok:
        return "yes"
    if any_ok:
        return f"no (primary), but `{label}` is listed later"
    return "no"


def render(truth_rows, rows, reports_dir):
    t = totals(rows)
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
        "finding in the same order.\n"
    )
    out.append("| Scenario | Planted flaw | Agent behaviour | Skill label | Confidence | Label correct? | Fix location | Location correct? |")
    out.append("|---|---|---|---|---|---|---|---|")
    for tr, r in zip(truth_rows, rows):
        mark = " †" if r["ambiguous"] else ""
        labels = ", ".join(f"`{x}`" for x in r["labels"])
        conf = " / ".join(r["confidences"]) or "n/a"
        locs = ", ".join(f"`{x}`" for x in r["locations"])
        out.append(
            f"| {r['scenario']}{mark} | {tr['planted_flaw']} | {tr['behaviour_short']} | {labels} | {conf} | "
            f"{_yn(r['label_ok'], r['label_any'], tr['expected_failure_type'])} (expected `{tr['expected_failure_type']}`) | "
            f"{locs} | {_yn(r['location_ok'], r['location_any'], tr['expected_fix_location'])} (expected `{tr['expected_fix_location']}`) |"
        )
    out.append("")
    n = t["n"]
    out.append("## Totals\n")
    out.append("| Measure | Result |")
    out.append("|---|---|")
    out.append(f"| Label accuracy (primary finding) | {t['label_strict']}/{n} |")
    out.append(f"| Label accuracy, expected label anywhere in the report | {t['label_any']}/{n} |")
    out.append(f"| Label accuracy, scenarios with a failure only | {t['label_failing'][0]}/{t['label_failing'][1]} |")
    out.append(f"| Label accuracy, without ambiguous rows | {t['label_firm'][0]}/{t['label_firm'][1]} |")
    out.append(f"| Fix-location accuracy (primary location) | {t['location_strict']}/{n} |")
    out.append(f"| Fix-location accuracy, expected location anywhere in the list | {t['location_any']}/{n} |")
    out.append(f"| Fix-location accuracy, scenarios with a failure only | {t['location_failing'][0]}/{t['location_failing'][1]} |")
    out.append(f"| Fix-location accuracy, without ambiguous rows | {t['location_firm'][0]}/{t['location_firm'][1]} |")
    out.append(f"| Clean traces that got a made-up failure (false positives), unambiguous clean traces | {t['false_pos_firm'][0]}/{t['false_pos_firm'][1]} |")
    out.append(f"| Same, counting the ambiguous clean trace (`undo_delivered_order`) as clean | {t['false_pos_all'][0]}/{t['false_pos_all'][1]} |")
    out.append(f"| Reports that suggested a system-prompt edit for a failure involving only one tool | {t['sys_prompt_single'][0]} of {t['sys_prompt_single'][1]} single-tool failures |")
    out.append(f"| Reports that suggested a system-prompt edit at all | {t['sys_prompt_any']} of {n} |")
    out.append("")
    out.append("## How to read this\n")
    out.append(
        "- The ground truth is not blind. Claude drafted it from the committed traces and `demo-agent/tools.py` after "
        "reading the reports. Treat the ambiguous rows as open.\n"
        "- A \"fix location\" is read from the report's `Location:` line. Reports name several locations in one line, so the "
        "first one named counts as primary. `server behaviour` is mapped to `error_message`. The reports have no "
        "explicit `fix_location` field yet (that is step 6), so this is a text parse and can be wrong for a phrasing it has not seen.\n"
        "- The system-prompt count looks only at the `Location:` line. Reports that mention the system prompt only to say "
        "the fix does not belong there are not counted.\n"
        "- Single-tool failures in the ground truth: those whose `tools_involved` has one entry and that are not clean.\n"
        "\n## What the table does not check\n\n"
        "Labels and locations only. Claims inside the reports are not scored. Three worth knowing before quoting a report:\n\n"
        "- `unneeded_lookup`: the report says the empty search result \"means the store does not list the book\". "
        "`demo-agent/tools.py` lists Dune (stock 22); the search missed it because it matches the query as a substring "
        "of the title or the author, not both together. The trace alone cannot show this.\n"
        "- `undo_delivered_order`: the report rates `wrong_tool` as medium because the trace has no order status. "
        "The order is delivered, so `start_return` was the right action.\n"
        "- `cancel_shipped_order` and `return_processing_order`: the reports use `demo-agent/tools.py` as evidence, "
        "which the skill's later rule (use only the trace being triaged) no longer allows.\n"
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
