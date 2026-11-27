import json

import triage


def rec(scenario, run, failure=False, flaw=False, errors=0, variant="fixed"):
    return {"variant": variant, "scenario": scenario, "run": run, "trace_id": f"{scenario}-{run}",
            "failure": failure, "flaw_triggered": flaw, "tool_errors": errors, "file": f"x/{scenario}/{run}.json"}


def test_select_takes_troubled_runs_and_the_first_clean_run():
    runs = [rec("a", 1, failure=True), rec("a", 2), rec("a", 3), rec("b", 1), rec("b", 2), rec("b", 3, errors=1),
            rec("c", 1, flaw=True), rec("c", 2, failure=True, flaw=True), rec("c", 3, flaw=True),
            rec("a", 1, variant="flawed", failure=True)]
    got = [(r["trace_id"], why) for r, why in triage.select_runs(runs, "fixed")]
    assert got == [("a-1", "troubled"), ("a-2", "clean check"),
                   ("b-3", "troubled"), ("b-1", "clean check"),
                   ("c-1", "troubled"), ("c-2", "troubled"), ("c-3", "troubled")]


def test_select_ignores_other_variants():
    assert triage.select_runs([rec("a", 1, variant="flawed")], "fixed") == []


def test_blind_removes_the_experiment_metadata_everywhere():
    trace = {"metadata": {"scenario_id": "s", "agent_variant": "fixed", "experiment": "e", "run": 2, "temperature": 0},
             "observations": [{"name": "x", "metadata": {"agent_variant": "fixed", "keep": 1,
                                                         "metadata.experiment": "e", "finish_reason": "stop"}}],
             "input": {"run": "not metadata"}}
    out = triage.blind(trace)
    assert out["metadata"] == {"scenario_id": "s"}
    assert out["observations"][0]["metadata"] == {"keep": 1, "finish_reason": "stop"}
    assert out["input"] == {"run": "not metadata"}
    assert trace["metadata"]["agent_variant"] == "fixed"  # the input is not modified


def test_dry_run_builds_an_isolated_command(tmp_path, monkeypatch):
    src = tmp_path / "t.json"
    src.write_text(json.dumps({"id": "t1", "metadata": {"agent_variant": "fixed"}}))
    monkeypatch.setattr(triage, "ROOT", tmp_path)
    record = {"trace_id": "t1", "file": "t.json"}
    cmd, result = triage.triage_one(record, "fixed", tmp_path / "work", dry_run=True)
    assert result is None
    assert cmd[:2] == ["claude", "-p"]
    assert "--setting-sources" in cmd and cmd[cmd.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in cmd and "claude-sonnet-5-5" in cmd
    copy = json.loads((tmp_path / "work" / "fixed" / "t1" / "t1.json").read_text())
    assert "agent_variant" not in copy["metadata"]
    assert not any("examples" in a or "experiments" in a for a in cmd[cmd.index("--allowedTools"):])
