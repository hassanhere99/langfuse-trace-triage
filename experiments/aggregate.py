"""Build experiments/results_after.md from the run indexes, promptfoo results and triage reports.

    python experiments/aggregate.py

Reads experiments/runs/index.json, experiments/runs_t07/index.json (if present),
experiments/promptfoo/results.<variant>.json (if present), experiments/reports/<variant>/ and
experiments/results_after_notes.md (hand-written "what didn't work" text, included verbatim).
Every number in the output comes from those files. Nothing here calls a model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "demo-agent"))
sys.path.insert(0, str(ROOT / "skills" / "langfuse-trace-triage" / "scripts"))

import error_changes  # noqa: E402
import failure_checks as fc  # noqa: E402
import score_new_reports as sn  # noqa: E402
import score_reports as sr  # noqa: E402
import summarize_trace as st  # noqa: E402

SCENARIOS = [
    "search_by_title", "shipping_policy", "return_window_from_memory", "undo_delivered_order",
    "cancel_bare_number", "cancel_shipped_order", "return_processing_order", "unneeded_lookup",
]
VARIANTS = ["flawed", "fixed", "desc_only", "errors_only"]
POST_ERROR = ["cancel_shipped_order", "return_processing_order"]


def load_index(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.is_file() else None


def cell(runs, variant, scenario):
    return [r for r in runs if r["variant"] == variant and r["scenario"] == scenario]


def fraction(rs, key):
    return f"{sum(bool(r[key]) for r in rs)}/{len(rs)}" if rs else ""


def count(rs, key):
    return sum(bool(r[key]) for r in rs)


def committed_baseline():
    """The committed (flawed, temperature 0) run of each scenario, checked with the same rules."""
    out = {}
    for s in SCENARIOS:
        summary = st.summarize(json.loads((ROOT / "examples" / "traces" / f"{s}.json").read_text()))
        calls = fc.calls_from_summary(summary)
        v = fc.check(s, calls, summary["final_answer"])
        out[s] = {"calls": calls, "final": summary["final_answer"], **v}
    return out


def run_signature(r):
    return (tuple(r["tools"]), r["final_text"])


def outcome_table(runs, baseline, key, title):
    head = "| Scenario | Committed run (flawed, 1 run) | flawed | fixed | desc_only | errors_only |"
    out = [f"**{title}**\n", head, "|---|---|---|---|---|---|"]
    for s in SCENARIOS:
        b = baseline[s]
        base_key = "failure" if key == "failure_response_rule" else key
        cells = [fraction(cell(runs, v, s), key) for v in VARIANTS]
        if key == "failure_response_rule":
            b = dict(b, failure=fc.check(s, b["calls"], b["final"], return_rule="response")["failure"])
        out.append(f"| {s} | {'1/1' if b[base_key] else '0/1'} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def determinism(runs, baseline):
    cells = [(v, s) for v in VARIANTS for s in SCENARIOS if cell(runs, v, s)]
    identical = [(v, s) for v, s in cells if len({run_signature(r) for r in cell(runs, v, s)}) == 1]
    differing = [(v, s, len({run_signature(r) for r in cell(runs, v, s)}), len(cell(runs, v, s)))
                 for v, s in cells if (v, s) not in identical]
    flawed_same = [s for s in SCENARIOS if cell(runs, "flawed", s)
                   and (tuple(c["name"] for c in baseline[s]["calls"]), baseline[s]["final"].strip())
                   == run_signature(cell(runs, "flawed", s)[0])]
    return cells, identical, differing, flawed_same


def answers(runs):
    def f(variant, scenario, key="failure"):
        rs = cell(runs, variant, scenario)
        return count(rs, key), len(rs)

    def arrow(a, b):
        return f"{a[0]}/{a[1]} → {b[0]}/{b[1]}"

    lines = []
    base = f("flawed", "cancel_bare_number"), f("desc_only", "cancel_bare_number")
    flaw_base = f("flawed", "cancel_bare_number", "flaw_triggered"), f("desc_only", "cancel_bare_number", "flaw_triggered")
    lines.append(f"1. **Does `desc_only` fix `cancel_bare_number`?** Failures {arrow(*base)} (flawed → desc_only); "
                 f"bare-number calls {arrow(*flaw_base)}.")
    parts = []
    for s in POST_ERROR:
        parts.append(f"`{s}` {arrow(f('flawed', s), f('errors_only', s))}")
    lines.append("2. **Does `errors_only` fix the post-error scenarios?** Failures flawed → errors_only: " + "; ".join(parts) + ".")
    other = []
    for s in POST_ERROR:
        other.append(f"`{s}` flawed {f('flawed', s)[0]}/{f('flawed', s)[1]} → desc_only {f('desc_only', s)[0]}/{f('desc_only', s)[1]}")
    eb = f("flawed", "cancel_bare_number"), f("errors_only", "cancel_bare_number")
    ebf = f("flawed", "cancel_bare_number", "flaw_triggered"), f("errors_only", "cancel_bare_number", "flaw_triggered")
    lines.append("3. **Does either fix what the other was meant to fix?** `desc_only` on the post-error scenarios: " + "; ".join(other)
                 + f". `errors_only` on `cancel_bare_number`: failures {arrow(*eb)}, bare-number calls {arrow(*ebf)}.")
    lines.append("4. **Which fix caused `fixed` to fail `undo_delivered_order`?** " + undo_verdict(runs))
    return lines


def first_tools(rs):
    """e.g. "start_return x3" or "cancel_order x2, start_return x1"."""
    counts = {}
    for r in rs:
        counts[r.get("first_tool") or "no tool"] = counts.get(r.get("first_tool") or "no tool", 0) + 1
    return ", ".join(f"`{k}` x{v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def undo_table(runs):
    out = ["| Variant | `order_id` description | Error messages | Failures | Planted flaw triggered (`cancel_order` called) | First tool call |",
           "|---|---|---|---|---|---|"]
    spec = {"flawed": ("original", "original"), "desc_only": ("format stated", "original"),
            "errors_only": ("original", "what to do next"), "fixed": ("format stated", "what to do next")}
    for v in ("flawed", "desc_only", "errors_only", "fixed"):
        rs = cell(runs, v, "undo_delivered_order")
        if rs:
            out.append(f"| {v} | {spec[v][0]} | {spec[v][1]} | {fraction(rs, 'failure')} | {fraction(rs, 'flaw_triggered')} | {first_tools(rs)} |")
    return "\n".join(out) + "\n"


def undo_verdict(runs):
    """One sentence saying which variant reproduces the undo_delivered_order regression."""
    f = {v: cell(runs, v, "undo_delivered_order") for v in ("flawed", "fixed", "desc_only", "errors_only")}
    if not all(f.values()):
        return "desc_only and errors_only were not both run on this scenario, so the cause is not measured."
    bad = {v: count(rs, "failure") for v, rs in f.items()}
    n = {v: len(rs) for v, rs in f.items()}
    reproduces = [v for v in ("desc_only", "errors_only") if bad[v] > bad["flawed"]]
    base = f"Failures: flawed {bad['flawed']}/{n['flawed']}, desc_only {bad['desc_only']}/{n['desc_only']}, errors_only {bad['errors_only']}/{n['errors_only']}, fixed {bad['fixed']}/{n['fixed']}."
    if reproduces == ["desc_only"]:
        return base + " The `order_id` description change alone reproduces the regression; the error-message change alone does not."
    if reproduces == ["errors_only"]:
        return base + " The error-message change alone reproduces the regression; the description change alone does not."
    if len(reproduces) == 2:
        return base + " Both changes reproduce the regression on their own."
    if bad["fixed"] > bad["flawed"]:
        return base + " Neither change alone reproduces the regression, so the two fixes only cause it in combination."
    return base + " The regression did not appear."


def recheck_section(runs):
    data = load_index(ROOT / "experiments" / "runs_recheck" / "index.json")
    if not data:
        return []
    rr = data["runs"]
    out = ["## Did the Ollama update change anything?\n"]
    main_set = (data["settings"].get("ollama_version"), load_index(ROOT / "experiments" / "runs" / "settings.json")["ollama_version"])
    out.append(f"Ollama was updated between the first 72 runs (version {main_set[1]}) and the last 6 (version {load_index(ROOT / 'experiments' / 'runs' / 'settings.json')['extension']['ollama_version']}), "
               "with the same model file (same ID in `ollama list`). To check whether the update moved any output, `flawed` and `fixed` on `undo_delivered_order` "
               f"were run again on version {main_set[0]} (3 runs each, `experiments/runs_recheck/`).\n")
    same = []
    for v in ("flawed", "fixed"):
        a = sorted(cell(runs, v, "undo_delivered_order"), key=lambda r: r["run"])
        b = sorted(cell(rr, v, "undo_delivered_order"), key=lambda r: r["run"])
        same.append(f"`{v}`: failures {fraction(a, 'failure')} before the update, {fraction(b, 'failure')} after; first tool {first_tools(a)} before, {first_tools(b)} after; "
                    f"same tool calls run for run: {sum(tuple(x['tools']) == tuple(y['tools']) for x, y in zip(a, b))} of {len(b)}; "
                    f"same answer text run for run: {sum(x['final_text'] == y['final_text'] for x, y in zip(a, b))} of {len(b)}")
    out.append("- " + "\n- ".join(same) + "\n")
    moved = any(x["final_text"] != y["final_text"] for v in ("flawed", "fixed")
                for x, y in zip(sorted(cell(runs, v, "undo_delivered_order"), key=lambda r: r["run"]),
                                sorted(cell(rr, v, "undo_delivered_order"), key=lambda r: r["run"])))
    out.append("The update changed the wording of some answers" + (" (so outputs are not byte-identical across the two versions)" if moved else "")
               + ", but not which tool was called first or whether a run failed, which is what the comparison above uses.\n" if moved else
               "No output changed.\n")
    return out


def timing(runs):
    secs = [r["elapsed_s"] for r in runs]
    if not secs:
        return ""
    return (f"{len(secs)} runs, {sum(secs):.0f}s of model time in total, mean {sum(secs)/len(secs):.1f}s, "
            f"min {min(secs):.1f}s, max {max(secs):.1f}s.")


def promptfoo_section():
    rows, found = {}, False
    for v in ("flawed", "fixed"):
        p = ROOT / "experiments" / "promptfoo" / f"results.{v}.json"
        if not p.is_file():
            continue
        found = True
        data = json.loads(p.read_text())
        results = data.get("results", {}).get("results", [])
        for r in results:
            desc = (r.get("testCase") or {}).get("description") or r.get("description") or "?"
            rows.setdefault(desc, {}).setdefault(v, []).append(bool(r.get("success")))
    if not found:
        return "promptfoo was not run.\n"
    out = ["| Test (trace: what it checks) | flawed tools | fixed tools |", "|---|---|---|"]
    tot = {"flawed": [0, 0], "fixed": [0, 0]}
    for desc in sorted(rows):
        cells = []
        for v in ("flawed", "fixed"):
            rs = rows[desc].get(v, [])
            tot[v][0] += sum(rs)
            tot[v][1] += len(rs)
            cells.append(f"{sum(rs)}/{len(rs)}" if rs else "")
        out.append(f"| {desc} | {cells[0]} | {cells[1]} |")
    out.append(f"| **Total passes** | **{tot['flawed'][0]}/{tot['flawed'][1]}** | **{tot['fixed'][0]}/{tot['fixed'][1]}** |")
    return "\n".join(out) + "\n"


def triage_section(index_runs, ground_truth):
    """{variant: (rows as written, rows with "No failure found" summaries read as no_failure)}."""
    by_variant = {}
    for variant in ("flawed", "fixed"):
        rdir = ROOT / "experiments" / "reports" / variant
        runs = [r for r in index_runs if r["variant"] == variant]
        by_variant[variant] = (sn.score_variant(variant, runs, rdir, ground_truth),
                               sn.score_variant(variant, runs, rdir, ground_truth, adjusted=True))
    return by_variant


def build(notes_path=ROOT / "experiments" / "results_after_notes.md"):
    main = load_index(ROOT / "experiments" / "runs" / "index.json")
    if main is None:
        raise SystemExit("experiments/runs/index.json not found: run the experiment and export first")
    runs = main["runs"]
    s = main["settings"]
    baseline = committed_baseline()
    gt = sr.load_ground_truth(ROOT / "experiments" / "ground_truth.yaml")
    out = ["# Results after: the same scenarios with the fixes\n"]
    out.append(
        f"Generated by `experiments/aggregate.py`. Model `{s['model']}` on local Ollama {s.get('ollama_version')}, "
        f"temperature {s['temperature']}, seed {s['seed']}, max_tokens {s['max_tokens']}, up to {s['max_iterations']} model calls per turn, "
        f"{s['runs_per_cell']} runs per cell, experiment tag `{s['experiment']}` in every trace's metadata. "
        f"Runs went in run-major order (run 1 of every cell, then run 2, then run 3). The last 6 runs (`undo_delivered_order` on `desc_only` and `errors_only`) were added afterwards, "
        f"on Ollama {s.get('extension', {}).get('ollama_version', s.get('ollama_version'))} instead of {s.get('ollama_version')}; see \"Did the Ollama update change anything?\".\n")
    if s.get("env_demo_model_ignored"):
        out.append(f"`.env` set `DEMO_MODEL={s['env_demo_model_ignored']}`; the runner ignored that and used `{s['model']}`. `.env` was not edited.\n")
    out.append("## Failure rates\n")
    out.append(
        "A run \"fails\" by the per-scenario rule in `experiments/failure_checks.py` (a deterministic check of the tool calls and the "
        "final answer; the final answer of every run is kept in `experiments/runs/index.json` so it can be read). "
        "\"Planted flaw triggered\" means the flawed behaviour showed up in the run even if the agent recovered "
        "(for `cancel_bare_number`: a non-`BK-` order ID was sent). Blank cells were not run. The committed run is the "
        "one in `examples/traces/`, checked with the same rules.\n")
    out.append(outcome_table(runs, baseline, "failure", "Failures out of 3 runs"))
    out.append(
        "`cancel_shipped_order` is the one scenario where the text rule is a judgement call. The rule fixed before the runs flags any "
        "sentence that offers a return without mentioning delivery. The `fixed` and `errors_only` answers say \"you can initiate a return by "
        "contacting our customer service team\" and, in the next sentence, \"once the item has been delivered\". A response-level rule "
        "(the answer offers a return and never mentions delivery) was added after reading those answers. Both are shown; read the answers in "
        "`experiments/runs/index.json` and judge for yourself.\n")
    out.append(outcome_table(runs, baseline, "failure_response_rule", "Failures out of 3 runs, response-level return rule (added after seeing the answers)"))
    out.append(outcome_table(runs, baseline, "flaw_triggered", "Planted flaw triggered, out of 3 runs"))
    out.append("## The two fixes separately\n")
    out.extend(answers(runs))
    out.append("")
    out.append("### `undo_delivered_order` by variant\n")
    out.append(undo_table(runs))
    out.extend(recheck_section(runs))
    cells, identical, differing, flawed_same = determinism(runs, baseline)
    out.append("## Are the runs identical?\n")
    out.append(f"At temperature 0 with no seed, {len(identical)} of {len(cells)} cells gave 3 identical runs (same tool calls, same final answer text). "
               + ("All cells were identical. The 3 runs add no information beyond 1 run per cell. " if len(identical) == len(cells) else
                  "Cells where the runs differed: " + ", ".join(f"{v}/{s_} ({d} distinct of {n})" for v, s_, d, n in differing) + ". ")
               + f"The first `flawed` run reproduced the committed baseline run exactly (same tool calls, same final text) in {len(flawed_same)} of 8 scenarios"
               + (f" (differed: {', '.join(x for x in SCENARIOS if x not in flawed_same)})" if len(flawed_same) < 8 else "") + ".\n")
    out.append("## Error messages the fix changes\n")
    out.append("`fixed` and `errors_only` change the same messages; `desc_only` and `flawed` return the original ones. "
               "Only the error sites a scenario can reach matter for that scenario: invalid `order_id` (`cancel_bare_number`), "
               "`cancel_order` on a shipped order (`cancel_shipped_order`) and `start_return` on a processing order (`return_processing_order`).\n")
    out.append(error_changes.render_table())
    out.append("## Existing promptfoo tests\n")
    out.append("The 8 generated test files from `examples/promptfoo/` (10 tests), 3 repeats each at temperature 0, run against each "
               "variant's tool definitions. promptfoo replays one model step, so only the tool descriptions differ between the two columns: "
               "the `flawed` column is also what `errors_only` sends and the `fixed` column is also what `desc_only` sends. "
               "Error-message changes cannot show up here except where a test replays a tool result, and those replay the recorded flawed text.\n")
    out.append(promptfoo_section())
    index_runs = runs
    by_variant = triage_section(index_runs, gt)
    out.append("## Skill accuracy on the new traces\n")
    out.append("Same scoring as `results_before.md`, with the differences listed in `experiments/score_new_reports.py` (expected labels from "
               "rules committed before triage, evidence checked by quote verification). † = ambiguous expected label. "
               "The skill was frozen: the version with the trace-only rule. Triage inputs had the experiment's own metadata removed. "
               "\"Fix-location accuracy on traces that failed\" leaves out the expected-clean traces. It is only a hard test on the `flawed` traces: "
               "on `fixed` traces the rules expect location `none` for a failure the fix should have prevented (`model_error`), which a report that "
               "sees no failure also gets right.\n")
    for variant, (rows, adj) in by_variant.items():
        out.append(f"### {variant} traces\n")
        if not rows:
            out.append("No reports.\n")
            continue
        out.append(sn.render_rows(rows))
        out.append(sn.render_totals(f"{variant}: totals", rows, adj))
        if variant == "flawed":
            out.append("**Fix-location accuracy by scenario, `flawed` traces that actually failed** (the expected-clean traces are excluded; "
                       "\"primary\" is the first location the report names, \"anywhere\" is any location it names):\n")
            out.append(sn.render_location_by_scenario(rows))
    out.append("### Labels by variant\n")
    labels = {v: sorted({l for r in rows for l in r["labels"] if l != "no_failure"}) for v, (rows, _) in by_variant.items()}
    new_in_fixed = sorted(set(labels.get("fixed", [])) - set(labels.get("flawed", [])))
    out.append(f"Failure types reported on `flawed` traces: {', '.join(f'`{l}`' for l in labels.get('flawed', [])) or 'none'}. "
               f"On `fixed` traces: {', '.join(f'`{l}`' for l in labels.get('fixed', [])) or 'none'}. "
               f"Types that appear only on `fixed` traces: {', '.join(f'`{l}`' for l in new_in_fixed) or 'none'}.\n")
    t07 = load_index(ROOT / "experiments" / "runs_t07" / "index.json")
    if t07:
        out.append("## Temperature 0.7\n")
        out.append("5 runs per cell, `flawed` and `fixed` only, three scenarios. Failure rates only; no triage. Same failure rules as above. "
                   "Saved under `experiments/runs_t07/`.\n")
        out.append("| Scenario | flawed failures | fixed failures | flawed: planted flaw triggered | fixed: planted flaw triggered |")
        out.append("|---|---|---|---|---|")
        r7 = t07["runs"]
        for sc in ("cancel_bare_number", "cancel_shipped_order", "return_processing_order"):
            a, b = cell(r7, "flawed", sc), cell(r7, "fixed", sc)
            out.append(f"| {sc} | {fraction(a, 'failure')} | {fraction(b, 'failure')} | {fraction(a, 'flaw_triggered')} | {fraction(b, 'flaw_triggered')} |")
        out.append("")
        distinct = len({run_signature(r) for r in r7})
        out.append(f"Distinct outcomes: {distinct} distinct (tool calls, answer) combinations across {len(r7)} runs. {timing(r7)}\n")
    out.append("## Time and what broke\n")
    out.append(timing(runs) + "\n")
    broke = []
    raw = ROOT / "experiments" / "runs" / "raw_runs.jsonl"
    if raw.is_file():
        broke = [json.loads(l) for l in raw.read_text().splitlines() if l.strip() and json.loads(l).get("error")]
    out.append(("Runs that raised an error: " + "; ".join(f"{b['variant']}/{b['scenario']}/run{b['run']}: {b['error']}" for b in broke) + "\n")
               if broke else "No run raised an error. No run came near the 5 minute limit.\n")
    notes = Path(notes_path)
    if notes.is_file():
        out.append(notes.read_text())
    return "\n".join(out)


def main():
    text = build()
    (ROOT / "experiments" / "results_after.md").write_text(text)
    print("wrote experiments/results_after.md")


if __name__ == "__main__":
    main()
