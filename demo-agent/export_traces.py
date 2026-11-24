"""Export demo traces from Langfuse into examples/traces/<scenario_id>.json.

Trace ids come from demo-agent/last_run.json, or from the command line. Each trace is fetched
with skills/langfuse-trace-triage/scripts/fetch_trace.py, stripped of account-specific
fields, and written as pretty JSON.

Usage:
    python demo-agent/export_traces.py                  # all traces in last_run.json
    python demo-agent/export_traces.py TRACE_ID ...     # specific trace ids
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "skills" / "langfuse-trace-triage" / "scripts"))

STRIP_KEYS = {"projectId", "htmlPath", "userId", "authorUserId", "createdByUserId", "release", "version"}
STRIP_METADATA_KEYS = {"resourceAttributes"}


def strip_account_fields(obj, in_metadata=False):
    """Recursively drop account-specific keys. Applies to the trace, observations and scores."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in STRIP_KEYS and not in_metadata:
                continue
            if in_metadata and k in STRIP_METADATA_KEYS:
                continue
            if isinstance(v, str) and k.lower().endswith("url") and v.startswith("http"):
                continue
            out[k] = strip_account_fields(v, in_metadata=(k == "metadata") or in_metadata)
        return out
    if isinstance(obj, list):
        return [strip_account_fields(v, in_metadata) for v in obj]
    return obj


def has_check_score(trace):
    return any(s.get("name") == "expected_tool_check" for s in trace.get("scores") or [])


def make_fetcher(fetch_trace, host, pk, sk):
    """Adapt to the fetch_trace signature. The skill script takes (trace_id, env_dict);
    an older planned form took (trace_id, host, public_key, secret_key)."""
    import inspect
    if len(inspect.signature(fetch_trace).parameters) == 2:
        env = {"LANGFUSE_HOST": host, "LANGFUSE_PUBLIC_KEY": pk, "LANGFUSE_SECRET_KEY": sk}
        return lambda tid: fetch_trace(tid, env)
    return lambda tid: fetch_trace(tid, host, pk, sk)


def fetch_with_retry(fetch, trace_id, attempts, delay):
    """Poll until the trace exists, has the expected_tool_check score and a stable observation count."""
    last, last_count = None, -1
    for i in range(1, attempts + 1):
        try:
            trace = fetch(trace_id)
        except Exception as exc:  # not ingested yet (404) or transient error
            print(f"  attempt {i}/{attempts}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if "HTTP 401" in str(exc) or "Missing environment" in str(exc):
                return None  # retrying will not help
            time.sleep(delay)
            continue
        count = len(trace.get("observations") or [])
        if has_check_score(trace) and count == last_count:
            return trace
        last, last_count = trace, count
        print(f"  attempt {i}/{attempts}: {count} observations, score present: {has_check_score(trace)}", file=sys.stderr)
        time.sleep(delay)
    if last is not None:
        print("  warning: gave up waiting for a stable trace with the score; exporting what was fetched", file=sys.stderr)
    return last


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace_ids", nargs="*", help="trace ids (default: all in last_run.json)")
    ap.add_argument("--out-dir", default=str(ROOT / "examples" / "traces"))
    ap.add_argument("--attempts", type=int, default=10)
    ap.add_argument("--delay", type=float, default=5.0, help="seconds between attempts")
    args = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from repo_env import langfuse_host, load_repo_env
    load_repo_env()  # Langfuse keys come only from the repo-root .env, never from the shell
    host = langfuse_host()
    pk, sk = os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]

    names = {}  # trace_id -> scenario_id
    if args.trace_ids:
        ids = args.trace_ids
    else:
        path = HERE / "last_run.json"
        if not path.exists():
            sys.exit(f"{path} not found. Run demo-agent/run_demo.py first or pass trace ids.")
        data = json.loads(path.read_text())
        ids = [t["trace_id"] for t in data["traces"]]
        names = {t["trace_id"]: t["scenario_id"] for t in data["traces"]}

    try:
        from fetch_trace import fetch_trace
    except ImportError as exc:
        sys.exit(f"Could not import fetch_trace from skills/langfuse-trace-triage/scripts/fetch_trace.py: {exc}")

    fetch = make_fetcher(fetch_trace, host, pk, sk)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for tid in ids:
        print(f"Fetching {tid}", file=sys.stderr)
        trace = fetch_with_retry(fetch, tid, args.attempts, args.delay)
        if trace is None:
            print(f"  could not fetch {tid}", file=sys.stderr)
            failed += 1
            continue
        scenario = names.get(tid) or (trace.get("metadata") or {}).get("scenario_id") or tid
        clean = strip_account_fields(trace)
        path = out_dir / f"{scenario}.json"
        path.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
        print(f"  wrote {path}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
