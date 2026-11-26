"""Run the frozen triage skill (claude -p) on selected experiment traces.

    python experiments/triage.py select --variant fixed            # print the selection
    python experiments/triage.py run --variant fixed [--limit N]   # triage them, save reports

Selection, per scenario: every run where something went wrong (the planted failure happened, the
planted flaw showed up, or a tool errored) plus the first clean run, as a false-positive check.

Isolation: each trace is copied into its own scratch directory under .context/triage_work/ with the
experiment's own metadata (agent_variant, experiment, run, temperature) removed, and claude runs there
with --setting-sources project, so it cannot read examples/, experiments/ (ground truth, results) or
this session's user settings and hooks. The skill is loaded from this repo with --plugin-dir. Reports go
to experiments/reports/<variant>/<trace_id>.md and the promptfoo tests to .../promptfoo/. Nothing in
examples/ is touched. The skill (prompt, failure list, fetch script) is frozen for this step.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLIND_KEYS = {"agent_variant", "experiment", "run", "temperature"}
MODEL = "claude-sonnet-5-5"
PROMPT = (
    "Use the langfuse-trace-triage skill to triage the exported trace at {trace}.\n"
    "Save the report in {out}/ and the promptfoo test case in {out}/promptfoo/.\n"
    "The agent that produced this trace ran against an OpenAI-compatible endpoint configured by the "
    "OPENAI_BASE_URL, OPENAI_API_KEY and DEMO_MODEL environment variables."
)


def select_runs(index_runs, variant):
    """(run record, reason) pairs for one variant: troubled runs, then one clean run per scenario."""
    chosen = []
    scenarios = []
    for r in index_runs:
        if r["variant"] == variant and r["scenario"] not in scenarios:
            scenarios.append(r["scenario"])
    for scenario in scenarios:
        runs = sorted((r for r in index_runs if r["variant"] == variant and r["scenario"] == scenario),
                      key=lambda r: r["run"])
        troubled = [r for r in runs if r["failure"] or r["flaw_triggered"] or r["tool_errors"]]
        clean = [r for r in runs if r not in troubled]
        chosen += [(r, "troubled") for r in troubled]
        if clean:
            chosen.append((clean[0], "clean check"))
    return chosen


def blind(obj, in_metadata=False):
    """Copy of a trace with the experiment's own metadata keys removed wherever they appear in metadata."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if in_metadata and (k in BLIND_KEYS or any(k.endswith("." + b) for b in BLIND_KEYS)):
                continue
            out[k] = blind(v, in_metadata or k == "metadata")
        return out
    if isinstance(obj, list):
        return [blind(v, in_metadata) for v in obj]
    return obj


def allowed_tools(out_rel):
    skill = ROOT / "skills" / "langfuse-trace-triage"
    # A leading "//" marks an absolute path in permission rules; a single "/" would be relative to the cwd.
    return ["Skill", "Read(./**)", f"Read(/{skill}/**)",
            "Write(./**)", "Edit(./**)", f"Bash(python3 {skill}/scripts/*)"]


def triage_one(record, variant, work_root, dry_run=False):
    trace_id = record["trace_id"]
    src = ROOT / record["file"]
    work = work_root / variant / trace_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    trace_copy = work / f"{trace_id}.json"
    trace_copy.write_text(json.dumps(blind(json.loads(src.read_text())), indent=2, ensure_ascii=False) + "\n")
    out_dir = ROOT / "experiments" / "reports" / variant
    cmd = ["claude", "-p", PROMPT.format(trace=trace_copy.name, out="."),
           "--plugin-dir", str(ROOT), "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--setting-sources", "project", "--permission-mode", "dontAsk",
           "--allowedTools", *allowed_tools("."), "--model", MODEL, "--no-session-persistence"]
    if dry_run:
        return cmd, None
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=900)
    elapsed = round(time.monotonic() - started, 1)
    (work / "claude_stdout.txt").write_text(proc.stdout)
    (work / "claude_stderr.txt").write_text(proc.stderr)
    report = work / f"{trace_id}.md"
    if proc.returncode != 0 or not report.exists():
        return cmd, {"trace_id": trace_id, "ok": False, "returncode": proc.returncode, "elapsed_s": elapsed,
                     "stderr": proc.stderr[-500:], "files": sorted(p.name for p in work.rglob("*") if p.is_file())}
    (out_dir / "promptfoo").mkdir(parents=True, exist_ok=True)
    shutil.copy2(report, out_dir / f"{trace_id}.md")
    for p in work.rglob("*"):
        if p.is_file() and p.suffix in (".yaml", ".yml", ".json") and p != trace_copy:
            shutil.copy2(p, out_dir / "promptfoo" / p.name)
    denied = "denied" in proc.stdout.lower() or "permission" in proc.stdout.lower()
    return cmd, {"trace_id": trace_id, "ok": True, "elapsed_s": elapsed, "mentions_permission_denial": denied}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["select", "run"])
    ap.add_argument("--variant", required=True)
    ap.add_argument("--runs-dir", default=str(ROOT / "experiments" / "runs"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    index = json.loads((Path(args.runs_dir) / "index.json").read_text())["runs"]
    chosen = select_runs(index, args.variant)
    if args.action == "select":
        for r, why in chosen:
            print(f"{r['scenario']:<26} run{r['run']} {r['trace_id']} {why:<11} failure={r['failure']} flaw={r['flaw_triggered']} errors={r['tool_errors']}")
        print(f"{len(chosen)} traces")
        return 0

    out_dir = ROOT / "experiments" / "reports" / args.variant
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "triage_log.jsonl"
    done = set()
    if log_path.exists():
        done = {json.loads(l)["trace_id"] for l in log_path.read_text().splitlines() if l.strip() and json.loads(l).get("ok")}
    work_root = ROOT / ".context" / "triage_work"
    todo = [(r, why) for r, why in chosen if r["trace_id"] not in done][: args.limit]
    for i, (r, why) in enumerate(todo, 1):
        cmd, result = triage_one(r, args.variant, work_root, args.dry_run)
        if args.dry_run:
            print(" ".join(cmd[:3]), "...")
            continue
        result.update(scenario=r["scenario"], run=r["run"], why=why)
        with log_path.open("a") as f:
            f.write(json.dumps(result) + "\n")
        print(f"[{i}/{len(todo)}] {r['scenario']} run{r['run']} {r['trace_id']}: {'ok' if result['ok'] else 'FAILED'} {result['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
