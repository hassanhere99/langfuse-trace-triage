"""The flawed and fixed variants of the demo agent's tools, and how the agent passes the variant on."""
import contextlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools

ROOT = Path(__file__).resolve().parent.parent
ORDER_ID_TOOLS = ["get_order_status", "cancel_order", "start_return"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("AGENT_VARIANT", raising=False)
    tools.reset_state()
    yield
    tools.reset_state()


def by_name(defs):
    return {t["function"]["name"]: t["function"] for t in defs}


def err(name, args, variant):
    result, is_error = tools.execute(name, args, variant)
    assert is_error, result
    return result["error"]


# --- selecting a variant ------------------------------------------------------------------

def test_default_variant_is_flawed():
    assert tools.resolve_variant() == "flawed"


def test_variant_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENT_VARIANT", "fixed")
    assert tools.resolve_variant() == "fixed"
    assert tools.tools_for() == tools.tools_for("fixed")
    monkeypatch.setenv("AGENT_VARIANT", " Flawed ")
    assert tools.resolve_variant() == "flawed"


def test_explicit_argument_beats_the_environment(monkeypatch):
    monkeypatch.setenv("AGENT_VARIANT", "fixed")
    assert tools.resolve_variant("flawed") == "flawed"


def test_unknown_variant_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="AGENT_VARIANT"):
        tools.resolve_variant("fixd")
    monkeypatch.setenv("AGENT_VARIANT", "nope")
    with pytest.raises(ValueError):
        tools.execute("search_books", {"query": "x"})


# --- flawed is the original, unchanged ---------------------------------------------------------

def test_flawed_tool_definitions_equal_the_committed_promptfoo_tools():
    committed = json.loads((ROOT / "examples" / "promptfoo" / "tools.json").read_text())
    assert tools.tools_for("flawed") == committed == tools.TOOLS


def test_flawed_error_messages_are_the_original_ones():
    assert err("get_order_status", {}, "flawed") == "Missing required argument: order_id"
    assert err("cancel_order", {"order_id": "10571"}, "flawed") == 'Invalid order_id: "10571"'
    assert err("cancel_order", {"order_id": "BK-99999"}, "flawed") == "Order not found: BK-99999"
    assert err("cancel_order", {"order_id": "BK-10388"}, "flawed") == "Order BK-10388 cannot be cancelled because its status is shipped."
    assert err("cancel_order", {"order_id": "BK-10234"}, "flawed") == "Order BK-10234 cannot be cancelled because its status is delivered."
    assert err("start_return", {"order_id": "BK-10571"}, "flawed") == "Order BK-10571 is not eligible for return because its status is processing."
    assert err("start_return", {"order_id": "BK-10388"}, "flawed") == "Order BK-10388 is not eligible for return because its status is shipped."
    assert err("search_books", {}, "flawed") == "Missing required argument: query"
    assert err("nope", {}, "flawed") == "Unknown tool: nope"
    assert err("search_books", [], "flawed") == "Tool arguments must be an object"


# --- fixed: change 1, the order_id format ---------------------------------------------------------

def test_fixed_order_id_description_states_the_format_in_every_tool_that_takes_one():
    fixed, flawed = by_name(tools.tools_for("fixed")), by_name(tools.tools_for("flawed"))
    for name in ORDER_ID_TOOLS:
        assert flawed[name]["parameters"]["properties"]["order_id"]["description"] == "The order ID"
        desc = fixed[name]["parameters"]["properties"]["order_id"]["description"]
        assert "BK- followed by 5 digits" in desc and "BK-10571" in desc
    assert [n for n, f in fixed.items() if "order_id" in f["parameters"]["properties"]] == ORDER_ID_TOOLS


def test_fixed_changes_nothing_else_in_the_definitions():
    flawed, fixed = tools.tools_for("flawed"), tools.tools_for("fixed")
    assert [t["function"]["name"] for t in flawed] == [t["function"]["name"] for t in fixed]
    for a, b in zip(flawed, fixed):
        a, b = json.loads(json.dumps(a)), json.loads(json.dumps(b))
        for t in (a, b):
            t["function"]["parameters"]["properties"].get("order_id", {}).pop("description", None)
        assert a == b


def test_cancel_and_return_descriptions_still_overlap_as_the_control():
    flawed, fixed = by_name(tools.tools_for("flawed")), by_name(tools.tools_for("fixed"))
    for name in ("cancel_order", "start_return"):
        assert fixed[name]["description"] == flawed[name]["description"]
    assert fixed["cancel_order"]["description"].startswith("Undo an order.")
    assert fixed["start_return"]["description"].startswith("Reverse an order.")


def test_building_the_fixed_tools_does_not_modify_the_flawed_ones():
    before = json.dumps(tools.TOOLS)
    tools.tools_for("fixed")
    assert json.dumps(tools.TOOLS) == before


# --- both variants: behaviour that must not change ------------------------------------------------------

@pytest.mark.parametrize("name,args", [
    ("search_books", {"query": "Dune"}),
    ("get_order_status", {"order_id": "BK-10388"}),
    ("start_return", {"order_id": "BK-10234", "reason": "x"}),
    ("get_store_policy", {"topic": "returns"}),
])
def test_successful_results_are_identical(name, args):
    assert tools.execute(name, args, "flawed") == tools.execute(name, args, "fixed")


def test_cancel_success_is_identical():
    flawed = tools.execute("cancel_order", {"order_id": "BK-10571"}, "flawed")
    tools.reset_state()
    assert tools.execute("cancel_order", {"order_id": "BK-10571"}, "fixed") == flawed


def test_fixed_does_not_loosen_order_id_validation():
    assert err("cancel_order", {"order_id": "10571"}, "fixed").startswith('Invalid order_id: "10571"')
    assert tools.execute("get_order_status", {"order_id": "BK-10571"}, "fixed")[1] is False


def test_search_books_limitation_is_left_alone_in_both_variants():
    for variant in ("flawed", "fixed"):
        assert tools.execute("search_books", {"query": "Dune by Frank Herbert"}, variant)[0]["count"] == 0
        assert tools.execute("search_books", {"query": "Dune"}, variant)[0]["count"] == 1


def test_dump_tools_command_line(capsys, monkeypatch):
    import runpy
    monkeypatch.setattr("sys.argv", ["tools.py", "--dump-tools", "--variant", "fixed"])
    runpy.run_path(str(ROOT / "demo-agent" / "tools.py"), run_name="__main__")
    dumped = json.loads(capsys.readouterr().out)
    assert dumped == tools.tools_for("fixed")


# --- the agent passes the variant to the model and to the tools -------------------------------------------

def _fake_model(calls_seen):
    def create(**kwargs):
        calls_seen.append(kwargs)
        if len(calls_seen) == 1:
            tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="start_return", arguments='{"order_id": "BK-10571"}'))
            msg = SimpleNamespace(content="", tool_calls=[tc])
            finish = "tool_calls"
        else:
            msg = SimpleNamespace(content="done", tool_calls=None)
            finish = "stop"
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=None)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class _Obs:
    def update(self, **kw):
        pass


class _FakeLangfuse:
    @contextlib.contextmanager
    def start_as_current_observation(self, **kw):
        yield _Obs()

    def get_current_trace_id(self):
        return "trace-1"


@pytest.mark.parametrize("variant", ["flawed", "fixed"])
def test_agent_uses_the_selected_variant(monkeypatch, variant):
    import agent
    seen_meta = []

    @contextlib.contextmanager
    def fake_propagate(**kw):
        seen_meta.append(kw)
        yield

    monkeypatch.setattr(agent, "get_client", lambda: _FakeLangfuse())
    monkeypatch.setattr(agent, "propagate_attributes", fake_propagate)
    calls = []
    result = agent.run_turn("start a return on BK-10571", "s", client=_fake_model(calls), model="m", variant=variant)

    assert result.final_text == "done"
    assert calls[0]["tools"] == tools.tools_for(variant)
    assert calls[0]["temperature"] == 0 and calls[0]["max_tokens"] == 4096
    tool_msg = next(m for m in calls[1]["messages"] if m["role"] == "tool")
    tool_message = json.loads(tool_msg["content"])["error"]
    assert tool_message == err("start_return", {"order_id": "BK-10571"}, variant)
    assert seen_meta[0]["metadata"] == {"scenario_id": "s", "agent_variant": variant}


def test_agent_reads_the_variant_from_the_environment(monkeypatch):
    import agent
    monkeypatch.setenv("AGENT_VARIANT", "fixed")
    monkeypatch.setattr(agent, "get_client", lambda: _FakeLangfuse())
    monkeypatch.setattr(agent, "propagate_attributes", lambda **kw: contextlib.nullcontext())
    calls = []
    agent.run_turn("x", "s", client=_fake_model(calls), model="m")
    assert calls[0]["tools"] == tools.tools_for("fixed")
