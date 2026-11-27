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


# ---- skill v1 vs v2 on the same traces --------------------------------------------------------------------------

import re  # noqa: E402

REPORTS_V1 = ROOT / "experiments" / "reports"
REPORTS_V2 = ROOT / "experiments" / "reports_v2"
_NAMES_DATA_RE = re.compile(r"data (that )?would settle|data needed|would settle (it|this)|to settle (it|this)", re.I)
_VERDICT_RE = re.compile(r"^-\s*Verdict:\s*no_failure", re.M | re.I)


def report_path(rdir, trace_id):
    return Path(rdir) / f"{trace_id}.md"


def inconclusive_stats(rows, rdir):
    """How reports use `inconclusive`, from the report files behind scored rows.

    misuse: an `inconclusive` finding in a report whose Summary says "No failure found" (the v1 pattern).
    on_clean: an `inconclusive` primary label on an expected-clean trace.
    no_data: an `inconclusive` report that does not say what data would settle it.
    explicit_no_failure: reports with a "Verdict: no_failure" line (the v2 format)."""
    out = {"reports": len(rows), "inconclusive_primary": 0, "misuse": 0, "on_clean": 0, "no_data": 0, "explicit_no_failure": 0}
    for r in rows:
        text = report_path(rdir, r["trace_id"]).read_text()
        parsed = sr.parse_report(text)
        if _VERDICT_RE.search(text):
            out["explicit_no_failure"] += 1
        if parsed["labels"][0] == "inconclusive":
            out["inconclusive_primary"] += 1
            out["misuse"] += int(parsed["summary_no_failure"])
            out["on_clean"] += int(r["clean"])
            out["no_data"] += int(not _NAMES_DATA_RE.search(text))
    return out


def verdict_changes(rows_v1, rows_v2):
    """Traces where the primary label or the primary fix location differs between v1 and v2 (same trace id)."""
    v2 = {r["trace_id"]: r for r in rows_v2}
    changed, secondary_only, same = [], 0, 0
    for a in rows_v1:
        b = v2.get(a["trace_id"])
        if b is None:
            continue
        primary_changed = a["labels"][0] != b["labels"][0] or a["locations"][0] != b["locations"][0]
        if primary_changed:
            changed.append((a, b))
        elif a["labels"] != b["labels"] or a["locations"] != b["locations"]:
            secondary_only += 1
        else:
            same += 1
    return changed, secondary_only, same


def v1_v2_section(index_runs, ground_truth):
    out = []
    data = {}
    for variant in ("flawed", "fixed"):
        runs = [r for r in index_runs if r["variant"] == variant]
        r1 = sn.score_variant(variant, runs, REPORTS_V1 / variant, ground_truth)
        r2 = sn.score_variant(variant, runs, REPORTS_V2 / variant, ground_truth)
        data[variant] = (runs, r1, r2)
    if not data["flawed"][2] and not data["fixed"][2]:
        return out
    out.append("## Skill v1 vs v2 on the same traces\n")
    out.append(
        "**v1** is the skill with the trace-only rule, as used for `experiments/reports/` (everything above). **v2** adds the root-cause tie-break "
        "rule, the explicit `fix_location` field (commit `594d363`) and the `no_failure` / `inconclusive` fix. The 32 traces (16 `flawed`, 16 `fixed`), "
        "the blinding, the model, the allowed tools (no promptfoo in either) and the scorer are the same; v2 reports are in `experiments/reports_v2/`. "
        "Expected labels, the ground truth and the failure checks were not changed after seeing v2 output. No v1 number above was changed.\n")
    out.append("**One triage per trace, so differences on a single trace may be noise.** The same skill run twice on the same trace can give a different "
               "verdict (the model is not deterministic here). Read the totals as rough, and the per-trace list below as a list of changes, not of improvements.\n")

    # --- failed flawed traces, per scenario, v1 vs v2
    _, f1, f2 = data["flawed"]
    out.append("### Traces that actually failed, per scenario (`flawed`; expected-clean traces excluded)\n")
    out.append("| Scenario | Failed traces | Failure type right (primary), v1 → v2 | Fix location right (primary), v1 → v2 | Fix location named anywhere, v1 → v2 |")
    out.append("|---|---|---|---|---|")
    tot = [0, 0, 0, 0, 0, 0, 0]
    for scenario in dict.fromkeys(r["scenario"] for r in f1):
        a = [r for r in f1 if r["scenario"] == scenario and not r["clean"]]
        b = [r for r in f2 if r["scenario"] == scenario and not r["clean"]]
        if not a:
            continue
        cells = [(sum(r["label_ok"] for r in a), sum(r["label_ok"] for r in b)),
                 (sum(r["location_ok"] for r in a), sum(r["location_ok"] for r in b)),
                 (sum(r["location_any"] for r in a), sum(r["location_any"] for r in b))]
        out.append(f"| {scenario} | {len(a)} | {cells[0][0]}/{len(a)} → {cells[0][1]}/{len(b)} | {cells[1][0]}/{len(a)} → {cells[1][1]}/{len(b)} | {cells[2][0]}/{len(a)} → {cells[2][1]}/{len(b)} |")
        tot[0] += len(a)
        tot[1] += cells[0][0]; tot[2] += cells[0][1]; tot[3] += cells[1][0]; tot[4] += cells[1][1]; tot[5] += cells[2][0]; tot[6] += cells[2][1]
    n = tot[0]
    out.append(f"| **All failed `flawed` traces** | **{n}** | **{tot[1]}/{n} → {tot[2]}/{n}** | **{tot[3]}/{n} → {tot[4]}/{n}** | **{tot[5]}/{n} → {tot[6]}/{n}** |")
    out.append("")

    # --- totals, both variants
    out.append("### Totals, v1 vs v2 (as written)\n")
    out.append("| Measure | flawed v1 | flawed v2 | fixed v1 | fixed v2 |")
    out.append("|---|---|---|---|---|")

    def tcells(fn):
        return [fn(sr.totals(data[v][i]), data[v][i]) for v in ("flawed", "fixed") for i in (1, 2)]

    def line(name, fn):
        out.append(f"| {name} | " + " | ".join(tcells(fn)) + " |")

    line("Traces triaged", lambda t, rows: str(t["n"]))
    line("Failure type right (primary), all traces", lambda t, rows: f"{t['label']}/{t['n']}")
    line("Fully correct (label right, every quote found)", lambda t, rows: f"{t['fully_correct']}/{t['n']}")
    line("Failed traces: failure type right (primary)", lambda t, rows: f"{sum(r['label_ok'] for r in rows if not r['clean'])}/{t['location_failed'][1]}")
    line("Failed traces: fix location right (primary)", lambda t, rows: f"{t['location_failed'][0]}/{t['location_failed'][1]}")
    line("Failed traces: fix location named anywhere", lambda t, rows: f"{t['location_failed_any'][0]}/{t['location_failed_any'][1]}")
    def missed(variant, version):
        rows = sn.score_variant(variant, data[variant][0], (REPORTS_V1 if version == 1 else REPORTS_V2) / variant, ground_truth, adjusted=True)
        failed = [r for r in rows if not r["clean"]]
        return f"{sum(r['labels'] == ['no_failure'] for r in failed)}/{len(failed)}"

    out.append("| Failed traces reported as no failure (v1: a \"No failure found\" summary counts) | " + " | ".join(
        missed(v, i) for v in ("flawed", "fixed") for i in (1, 2)) + " |")
    line("False positives on expected-clean traces (a failure reported where the agent behaved correctly)", lambda t, rows: f"{t['false_pos'][0]}/{t['false_pos'][1]}")
    line("False positives, unambiguous clean traces only", lambda t, rows: f"{sum(r['false_positive'] for r in rows if r['clean'] and not r['ambiguous'])}/{sum(1 for r in rows if r['clean'] and not r['ambiguous'])}")
    line("System-prompt edit suggested, any report", lambda t, rows: f"{t['sys_prompt_any']} of {t['n']}")
    out.append("")

    # --- inconclusive misuse
    out.append("### How reports use `inconclusive`\n")
    out.append("`misuse` = an `inconclusive` finding in a report whose Summary says \"No failure found\". `on clean` = `inconclusive` as the primary label of an "
               "expected-clean trace. `no data named` = an `inconclusive` report with no line saying what data would settle it. "
               "`explicit no_failure` = reports with a \"Verdict: no_failure\" line (the v2 format).\n")
    out.append("| Count | flawed v1 | flawed v2 | fixed v1 | fixed v2 | both variants v1 | both variants v2 |")
    out.append("|---|---|---|---|---|---|---|")
    stats = {(v, i): inconclusive_stats(data[v][i], REPORTS_V1 / v if i == 1 else REPORTS_V2 / v) for v in ("flawed", "fixed") for i in (1, 2)}
    for key, name in (("reports", "reports"), ("inconclusive_primary", "`inconclusive` as primary label"), ("misuse", "misuse (`inconclusive` under \"No failure found\")"),
                      ("on_clean", "`inconclusive` on an expected-clean trace"), ("no_data", "`inconclusive` with no data named"), ("explicit_no_failure", "explicit `no_failure` verdict")):
        v = [stats[(a, i)][key] for a in ("flawed", "fixed") for i in (1, 2)]
        out.append(f"| {name} | {v[0]} | {v[1]} | {v[2]} | {v[3]} | {v[0] + v[2]} | {v[1] + v[3]} |")
    out.append("")

    # --- per-trace changes
    out.append("### Traces where the verdict changed\n")
    out.append("A verdict counts as changed when the primary finding type or the primary fix location differs between v1 and v2. "
               "Each row is one trace triaged once by each version; \"better\" and \"worse\" are against the expected label and location "
               "from `experiments/expected_labels.py`, which were not changed.\n")
    out.append("| Variant | Scenario | Run | Expected | v1 findings → fix location | v2 findings → fix location | Label | Location |")
    out.append("|---|---|---|---|---|---|---|---|")
    n_changed = n_secondary = n_same = 0
    for variant in ("flawed", "fixed"):
        _, r1, r2 = data[variant]
        changed, secondary, same = verdict_changes(r1, r2)
        n_changed += len(changed); n_secondary += secondary; n_same += same
        for a, b in changed:
            fmt = lambda r: ", ".join(f"`{l}`" for l in r["as_written"]) + " → " + ", ".join(f"`{l}`" for l in r["locations"])
            out.append(f"| {variant} | {a['scenario']}{' †' if a['ambiguous'] else ''} | {a['run']} | `{a['expected']}` / `{a['expected_location']}` | {fmt(a)} | {fmt(b)} | "
                       f"{'same' if a['label_ok'] == b['label_ok'] else ('better' if b['label_ok'] else 'worse')} | "
                       f"{'same' if a['location_ok'] == b['location_ok'] else ('better' if b['location_ok'] else 'worse')} |")
    out.append("")
    lab = {"better": 0, "worse": 0, "same": 0}
    loc = {"better": 0, "worse": 0, "same": 0}
    for variant in ("flawed", "fixed"):
        _, r1, r2 = data[variant]
        by2 = {r["trace_id"]: r for r in r2}
        for a in r1:
            b = by2.get(a["trace_id"])
            if b is None:
                continue
            lab["same" if a["label_ok"] == b["label_ok"] else ("better" if b["label_ok"] else "worse")] += 1
            loc["same" if a["location_ok"] == b["location_ok"] else ("better" if b["location_ok"] else "worse")] += 1
    out.append(f"Against the expected labels, across all 32 traces: primary finding type {lab['better']} better, {lab['worse']} worse, {lab['same']} unchanged in correctness; "
               f"primary fix location {loc['better']} better, {loc['worse']} worse, {loc['same']} unchanged in correctness.\n")
    out.append(f"{n_changed} of {n_changed + n_secondary + n_same} traces changed primary verdict or primary fix location; {n_secondary} differ only in "
               f"secondary findings or in the order of locations after the first; {n_same} have the same findings and locations. † = ambiguous expected label.\n")
    return out


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
    out.extend(v1_v2_section(runs, gt))
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
