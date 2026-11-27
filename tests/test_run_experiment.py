import json
import sys
from collections import Counter

import pytest

import run_experiment as rx

CONTROLS = {"search_by_title", "shipping_policy", "return_window_from_memory"}


def test_main_plan_is_78_runs_with_the_requested_cells():
    plan = rx.PLANS["main"]
    items = rx.plan_runs(plan)
    assert len(items) == 78 and len(set(items)) == 78
    assert plan["temperature"] == 0 and plan["runs"] == 3
    by_variant = Counter(v for _, _, v in items)
    assert by_variant == {"flawed": 24, "fixed": 24, "desc_only": 15, "errors_only": 15}
    for variant in ("flawed", "fixed"):
        assert {s for _, s, v in items if v == variant} == set(rx.SCENARIO_ORDER)
    for variant in ("desc_only", "errors_only"):
        assert {s for _, s, v in items if v == variant} == {
            "cancel_bare_number", "cancel_shipped_order", "return_processing_order", "unneeded_lookup", "undo_delivered_order"}
    assert all(Counter(r for r, s, v in items if (s, v) == cell) == {1: 1, 2: 1, 3: 1}
               for cell in {(s, v) for _, s, v in items})


def test_t07_plan_is_30_runs_at_temperature_0_7():
    plan = rx.PLANS["t07"]
    items = rx.plan_runs(plan)
    assert plan["temperature"] == 0.7 and plan["runs"] == 5
    assert len(items) == 30
    assert {v for _, _, v in items} == {"flawed", "fixed"}
    assert {s for _, s, _ in items} == set(rx.THREE)
    assert plan["out"].name == "runs_t07"


def test_runs_are_ordered_run_major():
    runs = [r for r, _, _ in rx.plan_runs(rx.PLANS["main"])]
    assert runs == sorted(runs)


def test_every_plan_variant_and_scenario_exists():
    import tools
    from run_demo import SCENARIOS
    ids = {s[0] for s in SCENARIOS}
    for plan in rx.PLANS.values():
        for variant, scenarios in plan["variants"].items():
            assert variant in tools.VARIANTS
            assert set(scenarios) <= ids


def test_read_raw_ignores_blank_lines(tmp_path):
    p = tmp_path / "raw.jsonl"
    p.write_text('{"a": 1}\n\n{"a": 2}\n')
    assert rx.read_raw(p) == [{"a": 1}, {"a": 2}]
    assert rx.read_raw(tmp_path / "missing.jsonl") == []


def test_experiment_tag():
    assert rx.EXPERIMENT == "before-after-2026-11"
    assert rx.MODEL == "llama3.2:3b"
    assert rx.RUN_TIMEOUT_S == 300


def _raw(variant, scenario, run, trace_id, **kw):
    base = {"variant": variant, "scenario": scenario, "run": run, "trace_id": trace_id, "elapsed_s": 1.0,
            "failure": False, "flaw_triggered": False, "note": "n", "tools": [], "tool_errors": 0,
            "final_text": "t", "misleading_not_found": False, "tool_calls": []}
    base.update(kw)
    return base


def test_export_writes_run_files_and_index(tmp_path, monkeypatch):
    import export_traces as ex
    import repo_env

    out = tmp_path / "runs"
    out.mkdir()
    (out / "settings.json").write_text(json.dumps({"model": "m"}))
    rows = [_raw("flawed", "cancel_bare_number", 1, "t1", failure=True),
            {"variant": "fixed", "scenario": "cancel_bare_number", "run": 1, "error": "boom", "elapsed_s": 2},
            _raw("fixed", "cancel_bare_number", 1, "t2"),
            _raw("fixed", "cancel_bare_number", 2, "t3")]
    (out / "raw_runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(rx, "ROOT", tmp_path)
    monkeypatch.setattr(repo_env, "load_repo_env", lambda *a, **k: {})
    monkeypatch.setattr(repo_env, "langfuse_host", lambda: "https://example.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def fake_fetch(fetch, trace_id, attempts, delay):
        return {"id": trace_id, "projectId": "P", "observations": [], "scores": [], "metadata": {"agent_variant": "x"}}

    monkeypatch.setattr(ex, "fetch_with_retry", fake_fetch)
    assert rx.do_export("t", {"out": out}) == 0

    index = json.loads((out / "index.json").read_text())
    assert [(r["variant"], r["run"], r["trace_id"]) for r in index["runs"]] == [
        ("flawed", 1, "t1"), ("fixed", 1, "t2"), ("fixed", 2, "t3")]
    written = json.loads((out / "fixed" / "cancel_bare_number" / "run_1.json").read_text())
    assert written["id"] == "t2" and "projectId" not in written  # account fields stripped
    assert index["settings"] == {"model": "m"}
    assert index["runs"][0]["file"].endswith("flawed/cancel_bare_number/run_1.json")


def test_export_refuses_a_trace_with_a_leaked_key(tmp_path, monkeypatch, capsys):
    import export_traces as ex
    import repo_env

    out = tmp_path / "runs"
    out.mkdir()
    (out / "settings.json").write_text("{}")
    (out / "raw_runs.jsonl").write_text(json.dumps(_raw("flawed", "cancel_bare_number", 1, "t1")) + "\n")
    monkeypatch.setattr(rx, "ROOT", tmp_path)
    monkeypatch.setattr(repo_env, "load_repo_env", lambda *a, **k: {})
    monkeypatch.setattr(repo_env, "langfuse_host", lambda: "https://example.invalid")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(ex, "fetch_with_retry", lambda *a: {"id": "t1", "observations": [], "scores": [], "x": "pk-lf-123"})
    assert rx.do_export("t", {"out": out}) == 1
    assert not (out / "flawed").exists()
    assert "account-specific" in capsys.readouterr().err


def test_settings_record_the_pinned_model_not_the_env_one():
    """Regression: check_langfuse_project re-reads .env after the model is pinned; the runner must pin it again."""
    import inspect
    src = inspect.getsource(rx.do_runs)
    assert src.index("describe(*get_projects())") < src.rindex('os.environ["DEMO_MODEL"] = MODEL') < src.index("settings_for(plan_name, plan)")


def test_recheck_plan_is_the_ollama_version_control():
    plan = rx.PLANS["recheck"]
    items = rx.plan_runs(plan)
    assert len(items) == 6 and plan["temperature"] == 0 and plan["out"].name == "runs_recheck"
    assert {(s, v) for _, s, v in items} == {("undo_delivered_order", "flawed"), ("undo_delivered_order", "fixed")}


def test_extension_cells_are_in_the_main_plan_and_keep_the_run_keys_of_the_first_72():
    items = rx.plan_runs(rx.PLANS["main"])
    assert {(s, v) for _, s, v in items if s == "undo_delivered_order"} == {
        ("undo_delivered_order", v) for v in ("flawed", "fixed", "desc_only", "errors_only")}
