"""Build docs/article-assets/ from the committed data.

    python experiments/make_article_assets.py

Copies and extracts only. Every number in SUMMARY.md is computed from a file in the repo and is
listed with that file. Run it again after anything under experiments/ changes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "demo-agent"))
sys.path.insert(0, str(ROOT / "skills" / "langfuse-trace-triage" / "scripts"))

import aggregate as ag  # noqa: E402
import error_changes  # noqa: E402
import score_new_reports as sn  # noqa: E402
import score_reports as sr  # noqa: E402

OUT = ROOT / "docs" / "article-assets"
SCENARIO = "cancel_bare_number"
TRACE_ID = "4e30ecd2dd0cd2465c2fafac242f5a8c"
# Step 2 commits (see git log): the order_id fix with the switch, then the error messages.
ORDER_ID_COMMIT = "56433b6"
ERRORS_COMMIT = "16ff7a9"
SKILL_COMMIT = "594d363"


def rel(p):
    return str(Path(p).relative_to(ROOT))


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def timeline_excerpt():
    """About 15 lines of the compact timeline of the committed cancel_bare_number trace."""
    out = subprocess.run([sys.executable, str(ROOT / "skills/langfuse-trace-triage/scripts/summarize_trace.py"),
                          str(ROOT / "examples/traces/cancel_bare_number.json")], capture_output=True, text=True, check=True).stdout
    lines = [l for l in out.splitlines() if l.strip() and not l.strip().startswith(("start:", "model:", "input messages:"))]
    start = lines.index("USER MESSAGE")
    end = lines.index("ERRORS")
    return "\n".join(lines[start:end]) + "\n"


def frac(n, d):
    return f"{n}/{d}"


def build_summary():
    rows = []  # (section, claim, value, source)

    def add(section, claim, value, source):
        assert (ROOT / source).exists(), source
        rows.append((section, claim, str(value), source))

    # --- setup
    main = json.loads((ROOT / "experiments/runs/index.json").read_text())
    s = main["settings"]
    src = "experiments/runs/settings.json"
    add("Setup", "Model", s["model"], src)
    add("Setup", "Temperature, main runs", s["temperature"], src)
    add("Setup", "Seed", "none set" if s["seed"] is None else s["seed"], src)
    add("Setup", "max_tokens", s["max_tokens"], src)
    add("Setup", "Ollama version", s["ollama_version"], src)
    add("Setup", "Runs per scenario and variant", s["runs_per_cell"], src)
    runs = main["runs"]
    add("Setup", "Traces in the main batch (72 first, then 6 undo_delivered_order runs for desc_only and errors_only)", len(runs), "experiments/runs/index.json")
    t07 = json.loads((ROOT / "experiments/runs_t07/index.json").read_text())
    add("Setup", "Traces in the temperature 0.7 batch", len(t07["runs"]), "experiments/runs_t07/index.json")
    add("Setup", "Temperature, second batch", t07["settings"]["temperature"], "experiments/runs_t07/settings.json")
    secs = [r["elapsed_s"] for r in runs]
    add("Setup", "Model time for the 78 main runs (s)", f"{sum(secs):.0f}", "experiments/runs/index.json")
    add("Setup", "Slowest single run (s)", f"{max(secs):.1f}", "experiments/runs/index.json")

    # --- committed reports scored against ground truth
    gt = sr.load_ground_truth(ROOT / "experiments/ground_truth.yaml")
    scored = [sr.score_one(t, sr.parse_report((ROOT / "examples/reports" / f"{t['trace_id']}.md").read_text())) for t in gt]
    t = sr.totals(scored)
    src = "experiments/results_before.md"
    add("Committed reports (before)", "Label accuracy", frac(t["label"], t["n"]), src)
    add("Committed reports (before)", "Fully correct (label right, no false fact)", frac(t["fully_correct"], t["n"]), src)
    add("Committed reports (before)", "Fix-location accuracy", frac(t["location"], t["n"]), src)
    add("Committed reports (before)", "Reports whose evidence stayed inside the trace", frac(t["evidence_in_bounds"], t["n"]), src)
    add("Committed reports (before)", "False positives on clean-behaviour traces", frac(*t["false_pos"]), src)
    add("Committed reports (before)", "System-prompt edit suggested, failures involving one tool", f"{t['sys_prompt_single'][0]} of {t['sys_prompt_single'][1]}", src)
    add("Committed reports (before)", "System-prompt edit suggested, any report", f"{t['sys_prompt_any']} of {t['n']}", src)

    # --- failure rates
    baseline = ag.committed_baseline()
    src = "experiments/runs/index.json"
    for sc in ag.SCENARIOS:
        add("Failures out of 3 runs (temperature 0)", f"{sc}, committed run (1 run)", "1/1" if baseline[sc]["failure"] else "0/1", "examples/traces/" + sc + ".json")
        for v in ag.VARIANTS:
            rs = ag.cell(runs, v, sc)
            if rs:
                add("Failures out of 3 runs (temperature 0)", f"{sc}, {v}", ag.fraction(rs, "failure"), src)
    for sc in ("cancel_bare_number", "cancel_shipped_order", "return_processing_order"):
        for v in ag.VARIANTS:
            rs = ag.cell(runs, v, sc)
            if rs:
                add("Planted flaw triggered out of 3 runs", f"{sc}, {v}", ag.fraction(rs, "flaw_triggered"), src)
    for v in ("flawed", "fixed", "desc_only", "errors_only"):
        rs = ag.cell(runs, v, "cancel_shipped_order")
        add("cancel_shipped_order, response-level return rule", f"{v} failures", ag.fraction(rs, "failure_response_rule"), src)
    cells, identical, differing, same = ag.determinism(runs, baseline)
    add("Determinism", "Cells with 3 identical runs", frac(len(identical), len(cells)), src)
    add("Determinism", "Scenarios where the first flawed run matches the committed run exactly", frac(len(same), 8), src)

    # --- temperature 0.7
    r7 = t07["runs"]
    for sc in ("cancel_bare_number", "cancel_shipped_order", "return_processing_order"):
        for v in ("flawed", "fixed"):
            rs = ag.cell(r7, v, sc)
            add("Failures out of 5 runs (temperature 0.7)", f"{sc}, {v}", ag.fraction(rs, "failure"), "experiments/runs_t07/index.json")
    add("Failures out of 5 runs (temperature 0.7)", "Distinct (tool calls, answer) outcomes across the 30 runs",
        len({ag.run_signature(r) for r in r7}), "experiments/runs_t07/index.json")

    # --- promptfoo
    for v in ("flawed", "fixed"):
        p = ROOT / "experiments/promptfoo" / f"results.{v}.json"
        st = json.loads(p.read_text())["results"]["stats"]
        add("promptfoo, existing 10 tests x 3 repeats", f"{v} tool definitions: passed", frac(st["successes"], st["successes"] + st["failures"] + st["errors"]), rel(p))

    # --- skill accuracy on new traces
    gts = sr.load_ground_truth(ROOT / "experiments/ground_truth.yaml")
    for v in ("flawed", "fixed"):
        rruns = [r for r in runs if r["variant"] == v]
        rdir = ROOT / "experiments/reports" / v
        for name, adjusted in (("as written", False), ("'No failure found' read as no_failure", True)):
            rows_v = sn.score_variant(v, rruns, rdir, gts, adjusted=adjusted)
            tv = sr.totals(rows_v)
            sec = f"Skill on new {v} traces ({name})"
            add(sec, "Traces triaged", tv["n"], "experiments/results_after.md")
            add(sec, "Label accuracy", frac(tv["label"], tv["n"]), "experiments/results_after.md")
            add(sec, "Fix-location accuracy", frac(tv["location"], tv["n"]), "experiments/results_after.md")
            add(sec, "Fix-location accuracy on traces that failed, primary location", frac(*tv["location_failed"]), "experiments/results_after.md")
            add(sec, "Fix-location accuracy on traces that failed, right location named anywhere", frac(*tv["location_failed_any"]), "experiments/results_after.md")
            add(sec, "False positives on expected-clean traces", frac(*tv["false_pos"]), "experiments/results_after.md")
            add(sec, "System-prompt edit suggested, any report", f"{tv['sys_prompt_any']} of {tv['n']}", "experiments/results_after.md")

    # --- fix location by scenario on failed flawed traces
    flawed_rows = sn.score_variant("flawed", [r for r in runs if r["variant"] == "flawed"], ROOT / "experiments/reports/flawed", gts)
    for scenario, n, prim, anyl in sn.location_by_scenario(flawed_rows):
        sec = "Fix location on failed flawed traces, by scenario"
        add(sec, f"{scenario}: primary location right (of {n} failed traces)", frac(prim, n), "experiments/results_after.md")
        add(sec, f"{scenario}: right location named anywhere (of {n} failed traces)", frac(anyl, n), "experiments/results_after.md")

    # --- undo_delivered_order attribution and the Ollama control
    for v in ("flawed", "desc_only", "errors_only", "fixed"):
        rs = ag.cell(runs, v, "undo_delivered_order")
        add("undo_delivered_order by variant (temperature 0, 3 runs each)", f"{v}: failures", ag.fraction(rs, "failure"), "experiments/runs/index.json")
        add("undo_delivered_order by variant (temperature 0, 3 runs each)", f"{v}: first tool call", ag.first_tools(rs).replace("`", ""), "experiments/runs/index.json")
    rc = json.loads((ROOT / "experiments/runs_recheck/index.json").read_text())["runs"]
    for v in ("flawed", "fixed"):
        add("Ollama update control (undo_delivered_order, 3 runs each)", f"{v}: failures after the update", ag.fraction(ag.cell(rc, v, "undo_delivered_order"), "failure"), "experiments/runs_recheck/index.json")
    add("Ollama update control (undo_delivered_order, 3 runs each)", "Ollama version of the first 72 runs", s["ollama_version"], "experiments/runs/settings.json")
    add("Ollama update control (undo_delivered_order, 3 runs each)", "Ollama version of the 6 extension runs", s["extension"]["ollama_version"], "experiments/runs/settings.json")
    add("Ollama update control (undo_delivered_order, 3 runs each)", "Ollama version of the control runs", json.loads((ROOT / "experiments/runs_recheck/settings.json").read_text())["ollama_version"], "experiments/runs_recheck/settings.json")

    # --- error messages
    rows_e = error_changes.error_changes()
    add("Error messages the fix changes", "Error sites changed", len({r[0] for r in rows_e}), "experiments/error_changes.py")
    add("Error messages the fix changes", "Concrete messages changed", len(rows_e), "experiments/error_changes.py")
    add("Error messages the fix changes", "Error sites not changed", len(error_changes.UNCHANGED_PROBES), "experiments/error_changes.py")

    # --- tests
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True).stdout
    n_tests = [l for l in out.splitlines() if "tests collected" in l or " test" in l and "collected" in l]
    count = next((l.split()[0] for l in out.splitlines() if l.split() and l.split()[0].isdigit() and "test" in l), "?")
    add("Tests", "Tests collected by pytest", count, "tests/")
    return rows


def render_summary(rows):
    out = ["# Summary of numbers\n",
           "Every number the article could quote, with the file it comes from. `python experiments/make_article_assets.py` regenerates "
           "this file from the committed data, so none of these values is typed by hand. Read `experiments/results_after.md` for what "
           "the numbers do and do not show.\n",
           "## Read this first\n",
           "- **The skill change came after the measurements.** The tie-break rule and the explicit `fix_location` field were added in commit "
           f"`{SKILL_COMMIT}`, after every run, report and score in this experiment. Nothing was re-run with the changed skill.",
           "- **The committed reports in `examples/reports/` were made by an earlier version of the skill**, before the rule \"use only the "
           "trace being triaged\" (commit `9feb2e8`). The new reports in `experiments/reports/` used the skill with that rule and without the "
           f"step 6 change.",
           "- Failure rates come from regular-expression checks on the tool calls and final answers (`experiments/failure_checks.py`). "
           "At temperature 0 most cells are 3 identical runs, so a 3/3 is close to one observation.",
           "- `cancel_shipped_order` depends on which return rule you use; both are listed.",
           "- Ground truth and expected labels are partly judgement; see `experiments/ground_truth.yaml` and `experiments/expected_labels.py`.\n",
           ]
    section = None
    for sec, claim, value, source in rows:
        if sec != section:
            out.append(f"\n## {sec}\n")
            out.append("| Claim | Value | Source |")
            out.append("|---|---|---|")
            section = sec
        out.append(f"| {claim} | {value} | `{source}` |")
    out.append("")
    out.append("## Files in this folder\n")
    out.append("| File | What it is | Source |")
    out.append("|---|---|---|")
    out.append("| `timeline_excerpt.txt` | The compact timeline of the `cancel_bare_number` trace, from the user message to the final answer | `examples/traces/cancel_bare_number.json`, summarised by `skills/langfuse-trace-triage/scripts/summarize_trace.py` |")
    out.append("| `report_cancel_bare_number.md` | The committed report, copied byte for byte | `examples/reports/%s.md` |" % TRACE_ID)
    out.append(f"| `fix_order_id.diff` | `demo-agent/tools.py` in git commit `{ORDER_ID_COMMIT}`: the `AGENT_VARIANT` switch and the `order_id` format fix | `git diff {ORDER_ID_COMMIT}~1 {ORDER_ID_COMMIT} -- demo-agent/tools.py` |")
    out.append(f"| `fix_start_return_error.diff` | `demo-agent/tools.py` in git commit `{ERRORS_COMMIT}`: every error message that now says what to do next, including the `start_return` one | `git diff {ERRORS_COMMIT}~1 {ERRORS_COMMIT} -- demo-agent/tools.py` |")
    out.append("| `promptfoo_cancel_bare_number.yaml` | The generated test for this trace, copied byte for byte | `examples/promptfoo/%s.yaml` |" % TRACE_ID)
    return "\n".join(out) + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "timeline_excerpt.txt").write_text(timeline_excerpt())
    shutil.copyfile(ROOT / "examples/reports" / f"{TRACE_ID}.md", OUT / "report_cancel_bare_number.md")
    shutil.copyfile(ROOT / "examples/promptfoo" / f"{TRACE_ID}.yaml", OUT / "promptfoo_cancel_bare_number.yaml")
    (OUT / "fix_order_id.diff").write_text(git("diff", f"{ORDER_ID_COMMIT}~1", ORDER_ID_COMMIT, "--", "demo-agent/tools.py"))
    (OUT / "fix_start_return_error.diff").write_text(git("diff", f"{ERRORS_COMMIT}~1", ERRORS_COMMIT, "--", "demo-agent/tools.py"))
    (OUT / "SUMMARY.md").write_text(render_summary(build_summary()))
    print("wrote", rel(OUT))


if __name__ == "__main__":
    main()
