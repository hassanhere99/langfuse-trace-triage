"""Run the before/after experiment: scenarios x variants x runs against the local model, one trace each.

    python experiments/run_experiment.py --plan main      # 72 runs, temperature 0   -> experiments/runs/
    python experiments/run_experiment.py --plan t07       # 30 runs, temperature 0.7 -> experiments/runs_t07/
    python experiments/run_experiment.py --plan main --phase export    # only (re)export the traces

Phases: "run" talks to the model and Langfuse and appends one line per run to <out>/raw_runs.jsonl;
"export" fetches each trace back from Langfuse, strips account fields and writes
<out>/<variant>/<scenario>/run_<n>.json plus <out>/index.json. "all" does both.

Safety: Langfuse keys come only from the repo-root .env (see demo-agent/repo_env.py). Every trace
gets metadata experiment=before-after-2026-11, agent_variant, run and temperature, so the batch can be
filtered or deleted in Langfuse later. A run that takes more than 5 minutes stops the whole batch.
Runs already in raw_runs.jsonl are skipped, so the script can be restarted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo-agent"))
sys.path.insert(0, str(ROOT / "experiments"))

EXPERIMENT = "before-after-2026-11"
MODEL = "llama3.2:3b"
RUN_TIMEOUT_S = 300  # stop the batch if one run takes longer than this
OLLAMA_PREFIXES = ("http://localhost:11434", "http://127.0.0.1:11434")
OLLAMA_DEFAULTS = {"OPENAI_BASE_URL": "http://localhost:11434/v1", "OPENAI_API_KEY": "ollama"}

SCENARIO_ORDER = [
    "search_by_title", "shipping_policy", "undo_delivered_order", "cancel_bare_number",
    "return_window_from_memory", "cancel_shipped_order", "return_processing_order", "unneeded_lookup",
]
POST_ERROR_AND_FORMAT = ["cancel_bare_number", "cancel_shipped_order", "return_processing_order", "unneeded_lookup"]
THREE = ["cancel_bare_number", "cancel_shipped_order", "return_processing_order"]

PLANS = {
    "main": {
        "out": ROOT / "experiments" / "runs", "temperature": 0, "runs": 3,
        "variants": {"flawed": SCENARIO_ORDER, "fixed": SCENARIO_ORDER,
                     "desc_only": POST_ERROR_AND_FORMAT, "errors_only": POST_ERROR_AND_FORMAT},
    },
    "t07": {
        "out": ROOT / "experiments" / "runs_t07", "temperature": 0.7, "runs": 5,
        "variants": {"flawed": THREE, "fixed": THREE},
    },
}


def plan_runs(plan):
    """Ordered (run, scenario, variant) list: run-major, then scenario, then variant."""
    items = []
    for run in range(1, plan["runs"] + 1):
        for scenario in SCENARIO_ORDER:
            for variant, scenarios in plan["variants"].items():
                if scenario in scenarios:
                    items.append((run, scenario, variant))
    return items


def run_key(variant, scenario, run):
    return f"{variant}/{scenario}/{run}"


def read_raw(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def ollama_version(base_url):
    import urllib.request
    try:
        root = base_url.split("/v1")[0].rstrip("/")
        with urllib.request.urlopen(root + "/api/version", timeout=5) as r:
            return json.load(r).get("version")
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"


def settings_for(plan_name, plan):
    import importlib.metadata as md
    import agent
    base = os.environ["OPENAI_BASE_URL"]
    return {
        "experiment": EXPERIMENT, "plan": plan_name, "model": os.environ["DEMO_MODEL"],
        "base_url": base, "ollama_version": ollama_version(base),
        "temperature": plan["temperature"], "seed": None, "max_tokens": agent.MAX_TOKENS,
        "max_iterations": agent.MAX_ITERATIONS, "runs_per_cell": plan["runs"],
        "variants": {v: s for v, s in plan["variants"].items()},
        "system_prompt": agent.SYSTEM_PROMPT,
        "packages": {p: md.version(p) for p in ("openai", "langfuse")},
        "python": sys.version.split()[0],
    }


def do_runs(plan_name, plan):
    from repo_env import load_repo_env
    load_repo_env()
    # The experiment is pinned to llama3.2:3b on local Ollama, the setup of the committed traces.
    # .env is not edited. Whatever it sets for the model is ignored, and it is recorded below.
    env_model = os.environ.get("DEMO_MODEL")
    base = os.environ.get("OPENAI_BASE_URL")
    if base and not base.startswith(OLLAMA_PREFIXES):
        sys.exit(f"OPENAI_BASE_URL is {base!r}, not local Ollama. Stopping.")
    defaulted = [k for k, v in OLLAMA_DEFAULTS.items() if not os.environ.get(k)]
    for k in defaulted:
        os.environ[k] = OLLAMA_DEFAULTS[k]
    os.environ["DEMO_MODEL"] = MODEL
    if defaulted:
        print("Not set in .env, using the documented Ollama defaults for: " + ", ".join(defaulted), flush=True)
    if env_model != MODEL:
        print(f"DEMO_MODEL in .env is {env_model!r}; this experiment uses {MODEL!r} (not editing .env).", flush=True)

    from check_langfuse_project import describe, get_projects
    print(describe(*get_projects()))
    # check_langfuse_project re-reads .env, which puts DEMO_MODEL back; pin it again.
    os.environ["DEMO_MODEL"] = MODEL
    print(f"Model: {MODEL} at {os.environ['OPENAI_BASE_URL']}  temperature={plan['temperature']}  seed=None\n", flush=True)

    import openai
    import agent
    import failure_checks as fc
    import tools as bookstore
    from langfuse import get_client
    from run_demo import SCENARIOS

    messages = {sid: (msg, expected) for sid, msg, expected in SCENARIOS}
    out = plan["out"]
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / "raw_runs.jsonl"
    done = {run_key(r["variant"], r["scenario"], r["run"]) for r in read_raw(raw_path) if not r.get("error")}
    settings_path = out / "settings.json"
    if not settings_path.exists():
        settings = settings_for(plan_name, plan)
        settings["endpoint_vars_defaulted"] = defaulted
        settings["env_demo_model_ignored"] = env_model if env_model != MODEL else None
        settings["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    client = openai.OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"],
                           timeout=RUN_TIMEOUT_S + 30, max_retries=0)
    lf = get_client()
    todo = [(r, s, v) for r, s, v in plan_runs(plan) if run_key(v, s, r) not in done]
    print(f"{len(todo)} runs to do ({len(done)} already recorded)\n", flush=True)
    batch_start = time.monotonic()
    consecutive_errors = 0

    for i, (run, scenario, variant) in enumerate(todo, 1):
        message, expected = messages[scenario]
        bookstore.reset_state()
        started = time.monotonic()
        record = {"variant": variant, "scenario": scenario, "run": run, "temperature": plan["temperature"],
                  "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            result = agent.run_turn(
                message, scenario, client=client, model=MODEL, variant=variant, temperature=plan["temperature"],
                metadata={"experiment": EXPERIMENT, "run": run, "temperature": plan["temperature"]})
        except Exception as exc:  # noqa: BLE001
            record.update(error=f"{type(exc).__name__}: {exc}", elapsed_s=round(time.monotonic() - started, 1))
            with raw_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
            print(f"[{i}/{len(todo)}] {variant}/{scenario}/run{run}: BROKE after {record['elapsed_s']}s: {record['error']}", flush=True)
            consecutive_errors += 1
            if "timeout" in record["error"].lower() or "timed out" in record["error"].lower():
                print(f"STOP: a run hit the {RUN_TIMEOUT_S}s limit.", flush=True)
                lf.flush()
                sys.exit(3)
            if consecutive_errors >= 3:
                print("STOP: 3 failures in a row.", flush=True)
                lf.flush()
                sys.exit(4)
            continue
        consecutive_errors = 0
        elapsed = round(time.monotonic() - started, 1)
        called = [c["name"] for c in result.tool_calls]
        got, want = (called[0] if called else "none"), (expected or "none")
        lf.create_score(trace_id=result.trace_id, name="expected_tool_check", value=1 if got == want else 0,
                        data_type="NUMERIC",
                        comment=f"automated check by run_demo.py: expected first tool {want}, got {got}")
        verdict = fc.check(scenario, result.tool_calls, result.final_text)
        record.update(
            trace_id=result.trace_id, elapsed_s=elapsed, tools=called,
            tool_errors=sum(1 for c in result.tool_calls if c["is_error"]),
            tool_calls=[{"name": c["name"], "input": c["input"], "result": c["result"], "is_error": c["is_error"]}
                        for c in result.tool_calls],
            final_text=result.final_text, failure=verdict["failure"], flaw_triggered=verdict["flaw_triggered"],
            note=verdict["note"], misleading_not_found=fc.misleading_not_found(scenario, result.tool_calls, result.final_text))
        with raw_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        lf.flush()
        print(f"[{i}/{len(todo)}] {variant:<11} {scenario:<26} run{run} {elapsed:>5.1f}s "
              f"{'FAIL' if verdict['failure'] else 'ok  '} flaw={'Y' if verdict['flaw_triggered'] else 'n'} "
              f"tools={','.join(called) or '-'}", flush=True)
        if elapsed > RUN_TIMEOUT_S:
            print(f"STOP: that run took {elapsed}s (limit {RUN_TIMEOUT_S}s).", flush=True)
            sys.exit(3)
    lf.flush()
    total = round(time.monotonic() - batch_start)
    settings = json.loads(settings_path.read_text())
    settings["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings["last_batch_seconds"] = total
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"\nDone: {len(todo)} runs in {total}s", flush=True)


def do_export(plan_name, plan, attempts=12, delay=5.0):
    from repo_env import langfuse_host, load_repo_env
    load_repo_env()
    import export_traces as ex
    import failure_checks as fc
    from fetch_trace import fetch_trace

    out = plan["out"]
    rows = [r for r in read_raw(out / "raw_runs.jsonl") if not r.get("error")]
    seen, latest = set(), []
    for r in reversed(rows):  # keep the last record for each run
        k = run_key(r["variant"], r["scenario"], r["run"])
        if k not in seen:
            seen.add(k)
            latest.append(r)
    latest.reverse()
    fetch = ex.make_fetcher(fetch_trace, langfuse_host(), os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    index = []
    failed = 0
    for r in latest:
        path = out / r["variant"] / r["scenario"] / f"run_{r['run']}.json"
        entry = {k: r[k] for k in ("variant", "scenario", "run", "trace_id", "elapsed_s", "failure", "flaw_triggered",
                                   "note", "tools", "tool_errors", "final_text", "misleading_not_found")}
        entry["failure_response_rule"] = fc.check(r["scenario"], r["tool_calls"], r["final_text"], return_rule="response")["failure"]
        entry["file"] = str(path.relative_to(ROOT))
        if not path.exists():
            trace = ex.fetch_with_retry(fetch, r["trace_id"], attempts, delay)
            if trace is None:
                print(f"could not fetch {r['trace_id']}", file=sys.stderr)
                failed += 1
                continue
            pids = {s.get("projectId") for s in trace.get("scores") or [] if s.get("projectId")}
            pids |= {o.get("projectId") for o in trace.get("observations") or [] if o.get("projectId")}
            clean = ex.strip_account_fields(trace)
            leaks = [p for pid in (pids or {None}) for p in ex.find_leaks(clean, pid)]
            if leaks:
                print(f"not writing {path}: account-specific values left at {sorted(set(leaks))[:5]}", file=sys.stderr)
                failed += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
            print(f"wrote {path.relative_to(ROOT)}", flush=True)
        index.append(entry)
    settings = json.loads((out / "settings.json").read_text())
    (out / "index.json").write_text(json.dumps({"settings": settings, "runs": index}, indent=2, ensure_ascii=False) + "\n")
    print(f"index.json: {len(index)} runs, {failed} not exported")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", choices=sorted(PLANS), required=True)
    ap.add_argument("--phase", choices=["run", "export", "all"], default="all")
    args = ap.parse_args(argv)
    plan = PLANS[args.plan]
    if args.phase in ("run", "all"):
        do_runs(args.plan, plan)
    if args.phase in ("export", "all"):
        return do_export(args.plan, plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
