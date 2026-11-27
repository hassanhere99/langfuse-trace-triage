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


# --- fixed: change 2, errors say what to do next ----------------------------------------------------

def test_fixed_start_return_on_an_unshipped_order_says_to_cancel_instead():
    assert err("start_return", {"order_id": "BK-10571"}, "fixed") == (
        "Order BK-10571 has not shipped, so it can't be returned. It can be cancelled instead with cancel_order."
    )


@pytest.mark.parametrize("name,args,expected", [
    ("cancel_order", {"order_id": "BK-10388"}, "A return can be started once it has been delivered."),
    ("cancel_order", {"order_id": "BK-10234"}, "start_return"),
    ("start_return", {"order_id": "BK-10388"}, "once it has been delivered"),
    ("cancel_order", {"order_id": "10571"}, "BK- followed by 5 digits, e.g. BK-10571"),
    ("get_order_status", {"order_id": "10571"}, "BK- followed by 5 digits, e.g. BK-10571"),
    ("get_order_status", {}, "BK-10571"),
    ("get_order_status", {"order_id": "BK-99999"}, "Check the order ID"),
    ("search_books", {}, "Pass a title, author name or ISBN."),
    ("nope", {}, "Available tools: search_books"),
    ("search_books", [], "for example"),
])
def test_fixed_errors_say_what_to_do_next(name, args, expected):
    flawed_msg, fixed_msg = err(name, args, "flawed"), err(name, args, "fixed")
    assert expected in fixed_msg
    assert fixed_msg != flawed_msg


def test_fixed_cancelled_order_errors_need_no_further_action():
    tools.execute("cancel_order", {"order_id": "BK-10571"}, "fixed")  # cancels it
    assert "already cancelled" in err("cancel_order", {"order_id": "BK-10571"}, "fixed")
    assert "was cancelled" in err("start_return", {"order_id": "BK-10571"}, "fixed")


def test_the_policy_error_already_said_what_to_do_and_is_unchanged():
    assert err("get_store_policy", {"topic": "x"}, "fixed") == err("get_store_policy", {"topic": "x"}, "flawed")


# --- both variants: behaviour that must not change ------------------------------------------------------

@pytest.mark.parametrize("name,args", [
    ("search_books", {"query": "Dune"}),
    ("get_order_status", {"order_id": "BK-10388"}),
    ("start_return", {"order_id": "BK-10234", "reason": "x"}),
    ("get_store_policy", {"topic": "returns"}),
])
def test_successful_results_are_identical(name, args):
    results = {v: tools.execute(name, args, v) for v in tools.VARIANTS}
    assert all(r == results["flawed"] for r in results.values())


def test_cancel_success_is_identical():
    flawed = tools.execute("cancel_order", {"order_id": "BK-10571"}, "flawed")
    tools.reset_state()
    for v in tools.VARIANTS:
        tools.reset_state()
        assert tools.execute("cancel_order", {"order_id": "BK-10571"}, v) == flawed


@pytest.mark.parametrize("variant", tools.VARIANTS)
def test_no_variant_loosens_order_id_validation(variant):
    assert err("cancel_order", {"order_id": "10571"}, variant).startswith('Invalid order_id: "10571"')
    assert tools.execute("get_order_status", {"order_id": "BK-10571"}, variant)[1] is False


def test_search_books_limitation_is_left_alone_in_every_variant():
    for variant in tools.VARIANTS:
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


@pytest.mark.parametrize("variant", tools.VARIANTS)
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


# --- the two fixes are separable: desc_only and errors_only ------------------------------------------

import error_changes  # noqa: E402  (experiments/ is on the path via conftest)


def diff_paths(a, b, path=""):
    """Paths at which two JSON-like structures differ."""
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}")
            else:
                out += diff_paths(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in diff_paths(x, y, f"{path}[{i}]")]
    return [] if a == b else [path]


ORDER_ID_PATHS = [
    f"[{i}]/function/parameters/properties/order_id/description"
    for i, t in enumerate(tools.TOOLS) if t["function"]["name"] in ORDER_ID_TOOLS
]


def test_all_four_variants_exist():
    assert tools.VARIANTS == ("flawed", "fixed", "desc_only", "errors_only")


def test_definitions_differ_from_flawed_only_where_each_variant_claims():
    flawed = tools.tools_for("flawed")
    assert len(ORDER_ID_PATHS) == 3
    assert diff_paths(flawed, tools.tools_for("fixed")) == ORDER_ID_PATHS
    assert diff_paths(flawed, tools.tools_for("desc_only")) == ORDER_ID_PATHS
    assert diff_paths(flawed, tools.tools_for("errors_only")) == []


def test_desc_only_changes_no_error_message():
    for site, name, tool, args, setup in error_changes.PROBES:
        assert error_changes.run_probe("desc_only", tool, args, setup) == error_changes.run_probe("flawed", tool, args, setup), name
    for name, tool, args, setup in error_changes.UNCHANGED_PROBES:
        assert error_changes.run_probe("desc_only", tool, args, setup) == error_changes.run_probe("flawed", tool, args, setup)


def test_errors_only_changes_exactly_the_errors_fixed_changes():
    for site, name, tool, args, setup in error_changes.PROBES:
        flawed_msg = error_changes.run_probe("flawed", tool, args, setup)
        fixed_msg = error_changes.run_probe("fixed", tool, args, setup)
        assert fixed_msg != flawed_msg, name
        assert fixed_msg.startswith(flawed_msg.split(".")[0].split(" because")[0].split(", so")[0][:12]), name
        assert error_changes.run_probe("errors_only", tool, args, setup) == fixed_msg, name
    for name, tool, args, setup in error_changes.UNCHANGED_PROBES:
        assert error_changes.run_probe("errors_only", tool, args, setup) == error_changes.run_probe("flawed", tool, args, setup)


def test_probe_counts_match_the_error_sites_in_tools_py():
    """Keep in sync with tools.py: 9 error sites, of which 8 change (12 messages) and 1 does not."""
    assert len({p[0] for p in error_changes.PROBES}) == 8
    assert len(error_changes.PROBES) == 12
    assert len(error_changes.UNCHANGED_PROBES) == 1


def test_errors_only_agent_sends_flawed_tools_and_fixed_errors(monkeypatch):
    import agent
    monkeypatch.setattr(agent, "get_client", lambda: _FakeLangfuse())
    monkeypatch.setattr(agent, "propagate_attributes", lambda **kw: contextlib.nullcontext())
    calls = []
    agent.run_turn("x", "s", client=_fake_model(calls), model="m", variant="errors_only")
    assert calls[0]["tools"] == tools.TOOLS
    tool_msg = next(m for m in calls[1]["messages"] if m["role"] == "tool")
    assert "cancel_order" in json.loads(tool_msg["content"])["error"]


def test_agent_temperature_and_metadata_are_passed_through(monkeypatch):
    import agent
    seen = []

    @contextlib.contextmanager
    def fake_propagate(**kw):
        seen.append(kw)
        yield

    monkeypatch.setattr(agent, "get_client", lambda: _FakeLangfuse())
    monkeypatch.setattr(agent, "propagate_attributes", fake_propagate)
    calls = []
    agent.run_turn("x", "s", client=_fake_model(calls), model="m", variant="flawed", temperature=0.7,
                   metadata={"experiment": "e", "run": 2})
    assert calls[0]["temperature"] == 0.7
    assert seen[0]["metadata"] == {"scenario_id": "s", "agent_variant": "flawed", "experiment": "e", "run": 2}


# --- promptfoo configs for the experiment ----------------------------------------------------------------

@pytest.mark.parametrize("variant", ["flawed", "fixed"])
def test_experiment_promptfoo_tools_are_generated_from_tools_py(variant):
    path = ROOT / "experiments" / "promptfoo" / f"tools.{variant}.json"
    assert json.loads(path.read_text()) == tools.tools_for(variant)


@pytest.mark.parametrize("variant", ["flawed", "fixed"])
def test_experiment_promptfoo_configs_run_the_same_tests_as_the_committed_config(variant):
    def tests(path):
        return re.findall(r"- file://(?:\.\./\.\./examples/promptfoo/)?(\S+\.yaml)", path.read_text())

    committed = tests(ROOT / "examples" / "promptfoo" / "promptfooconfig.yaml")
    mine = tests(ROOT / "experiments" / "promptfoo" / f"promptfooconfig.{variant}.yaml")
    assert len(committed) == 8 and mine == committed
    text = (ROOT / "experiments" / "promptfoo" / f"promptfooconfig.{variant}.yaml").read_text()
    assert f"tools: file://tools.{variant}.json" in text and "temperature: 0\n" in text
