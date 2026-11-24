import json
import subprocess
import sys
from pathlib import Path

import pytest

import summarize_trace as st

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = ROOT / "skills" / "langfuse-trace-triage" / "scripts" / "summarize_trace.py"
EXAMPLE_TRACES = sorted((ROOT / "examples" / "traces").glob("*.json"))


def load(name):
    return json.loads((FIXTURES / name).read_text())


def tool_steps(summary):
    return [s for s in summary["steps"] if s["kind"] == "tool_call"]


def generation_steps(summary):
    return [s for s in summary["steps"] if s["kind"] == "generation"]


def test_normal_anthropic_tool_use():
    s = st.summarize(load("anthropic_tool_use.json"))
    assert s["trace"]["id"] == "tr-normal-0001"
    assert s["user_message"] == "Where is my order BK-1042?"
    assert [x["kind"] for x in s["steps"]] == ["generation", "tool_call", "generation"]
    gen1 = generation_steps(s)[0]
    assert gen1["model"] == "claude-haiku-5-5"
    assert gen1["tool_calls_requested"][0]["name"] == "get_order_status"
    assert "BK-1042" in gen1["tool_calls_requested"][0]["arguments"]
    (tool,) = tool_steps(s)
    assert tool["name"] == "get_order_status"
    assert json.loads(tool["arguments"]) == {"order_id": "BK-1042"}
    assert "shipped" in tool["result"]
    assert tool["is_error"] is False
    assert s["errors"] == []
    assert s["final_answer"].startswith("Your order BK-1042 has shipped")
    assert s["scores"][0]["name"] == "expected_tool_check"
    assert s["scores"][0]["value"] == 1
    assert "automated check" in s["scores"][0]["comment"]


def test_tools_available_has_full_descriptions_and_schema():
    s = st.summarize(load("anthropic_tool_use.json"), max_chars=10)
    names = [t["name"] for t in s["tools_available"]]
    assert names == ["search_books", "get_order_status"]
    # descriptions are never truncated, even with a tiny --max-chars
    assert s["tools_available"][0]["description"].endswith("with price and stock.")
    assert s["tools_available"][1]["input_schema"]["required"] == ["order_id"]
    text = st.render_text(s)
    assert "TOOLS AVAILABLE" in text
    assert "Look up an order by its ID and return status and shipping details." in text


def test_no_tool_calls():
    s = st.summarize(load("no_tool_calls.json"))
    assert tool_steps(s) == []
    assert generation_steps(s)[0]["tool_calls_requested"] == []
    assert s["user_message"] == "What are your opening hours?"
    assert s["final_answer"].startswith("We are open")
    assert s["scores"] == []
    assert "tool calls: 0" in st.render_text(s)


def test_tool_error():
    s = st.summarize(load("tool_error.json"))
    (tool,) = tool_steps(s)
    assert tool["is_error"] is True
    assert "not found" in tool["status_message"]
    assert s["errors"] and s["errors"][0]["level"] == "ERROR"
    assert s["errors"][0]["observation"] == "tool:get_order_status"
    assert "ERROR" in st.render_text(s)


def test_error_recovered_from_tool_result_without_tool_observation():
    s = st.summarize(load("wrapper_no_tool_observations.json"))
    (tool,) = tool_steps(s)
    assert tool["source"] == "generation_output"
    assert tool["is_error"] is True
    assert "timed out" in tool["result"]
    assert s["errors"]
    assert s["scores"][0]["comment"] == "thumbs down"
    assert s["trace"]["id"] == "tr-wrap-0008"


def test_multiple_generations_sorted_by_start_time():
    # fixture file order is shuffled on purpose
    data = load("multiple_generations.json")
    assert data["observations"][0]["name"] == "llm-call-3"
    s = st.summarize(data)
    assert [g["name"] for g in generation_steps(s)] == ["llm-call-1", "llm-call-2", "llm-call-3"]
    assert [t["name"] for t in tool_steps(s)] == ["search_books", "get_order_status"]
    # span named tool:* is treated as a tool call, and no duplicate is made from generation output
    assert len(tool_steps(s)) == 2
    kinds = [x["kind"] for x in s["steps"]]
    assert kinds == ["generation", "tool_call", "generation", "tool_call", "generation"]


def test_minimal_trace_with_missing_fields():
    s = st.summarize(load("minimal.json"))
    assert s["trace"]["id"] == "tr-min-0005"
    assert s["trace"]["timestamp"] is None
    assert s["user_message"] == ""
    assert s["final_answer"] == ""
    assert s["tools_available"] == []
    text = st.render_text(s)
    assert "not recorded in the trace" in text
    assert "(not found in trace)" in text


@pytest.mark.parametrize("data", [{}, {"observations": None}, {"observations": ["a-string-id", 3]}, []])
def test_empty_and_odd_inputs_do_not_crash(data):
    s = st.summarize(data)
    assert s["steps"] == []
    st.render_text(s)


def test_null_input_output_and_unknown_type():
    data = {
        "id": "t",
        "input": None,
        "output": None,
        "observations": [
            {"id": "a", "type": "AGENT", "name": "planner", "input": None, "output": None},
            {"id": "b", "type": "TOOL", "name": "lookup", "input": None, "output": None, "level": "WARNING"},
        ],
    }
    s = st.summarize(data)
    assert [t["name"] for t in tool_steps(s)] == ["lookup"]
    assert s["errors"][0]["level"] == "WARNING"


def test_list_of_observations_input():
    s = st.summarize(load("observations_list.json"))
    assert s["user_message"] == "Any books by Ana Ruiz?"
    assert generation_steps(s)[0]["tool_calls_requested"][0]["name"] == "search_books"
    assert [t["name"] for t in tool_steps(s)] == ["search_books"]
    assert tool_steps(s)[0]["result"] == "[]"


def test_openai_style_tool_calls():
    s = st.summarize(load("openai_tool_calls.json"))
    gen1, gen2 = generation_steps(s)
    assert gen1["tool_calls_requested"][0]["name"] == "get_order_status"
    assert json.loads(gen1["tool_calls_requested"][0]["arguments"]) == {"order_id": "BK-3003"}
    (tool,) = tool_steps(s)
    assert tool["source"] == "generation_output"
    assert "delivered" in tool["result"]
    assert gen2["text"] == "BK-3003 was delivered."
    assert s["user_message"] == "Track BK-3003"
    assert s["tools_available"][0]["name"] == "get_order_status"
    assert s["tools_available"][0]["description"] == "Look up an order by its ID."
    assert s["system_prompt"].startswith("You are a support assistant")


def test_error_looking_output_without_error_level():
    data = {
        "observations": [
            {"id": "t1", "type": "SPAN", "name": "tool:cancel_order", "startTime": "2026-01-01T00:00:00Z",
             "input": {"order_id": "BK-1"}, "output": {"error": "order already shipped"}}
        ]
    }
    s = st.summarize(data)
    assert tool_steps(s)[0]["is_error"] is True
    assert s["errors"]


def test_max_chars_truncates_results_but_not_zero():
    long_result = "x" * 2000
    data = {"observations": [{"id": "t1", "type": "TOOL", "name": "tool:search_books", "output": long_result}]}
    short = tool_steps(st.summarize(data, max_chars=100))[0]["result"]
    assert "truncated" in short and len(short) < 200
    full = tool_steps(st.summarize(data, max_chars=0))[0]["result"]
    assert full == long_result


def test_trace_input_as_messages_dict():
    data = {"input": {"messages": [{"role": "user", "content": "hello there"}]}, "observations": []}
    assert st.summarize(data)["user_message"] == "hello there"


def test_cli_text_json_and_stdin(tmp_path):
    path = FIXTURES / "anthropic_tool_use.json"
    text = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, check=True).stdout
    assert "Where is my order BK-1042?" in text
    as_json = subprocess.run([sys.executable, str(SCRIPT), str(path), "--json"], capture_output=True, text=True, check=True).stdout
    assert json.loads(as_json)["trace"]["id"] == "tr-normal-0001"
    piped = subprocess.run([sys.executable, str(SCRIPT), "-", "--max-chars", "50"], input=path.read_text(),
                           capture_output=True, text=True, check=True).stdout
    assert "TIMELINE" in piped


def test_cli_bad_file_exits_nonzero(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    res = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True)
    assert res.returncode == 1 and "error:" in res.stderr


def test_same_start_time_orders_by_end_time():
    obs = [
        {"id": "g2", "type": "GENERATION", "name": "llm-call-2",
         "startTime": "2026-01-01T00:00:01.000Z", "endTime": "2026-01-01T00:00:05.000Z"},
        {"id": "t1", "type": "TOOL", "name": "tool:x",
         "startTime": "2026-01-01T00:00:01.000Z", "endTime": "2026-01-01T00:00:01.000Z"},
        {"id": "g1", "type": "GENERATION", "name": "llm-call-1",
         "startTime": "2026-01-01T00:00:00.000Z", "endTime": "2026-01-01T00:00:01.000Z"},
    ]
    assert [o["id"] for o in st.order_observations(obs)] == ["g1", "t1", "g2"]


@pytest.mark.skipif(not EXAMPLE_TRACES, reason="no files in examples/traces yet")
@pytest.mark.parametrize("path", EXAMPLE_TRACES, ids=lambda p: p.name)
def test_example_traces_summarize_and_find_user_message(path):
    data = json.loads(path.read_text())
    s = st.summarize(data)
    assert s["user_message"].strip(), "user message not found in %s" % path.name
    assert st.render_text(s)
