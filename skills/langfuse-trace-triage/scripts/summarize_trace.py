#!/usr/bin/env python3
"""Print a compact, ordered timeline of a Langfuse trace.

Input: a trace JSON file (or `-` for stdin). Accepted shapes:
  - the Langfuse trace body (TraceWithFullDetails: id, timestamp, name, input, output,
    observations[], scores[], ...), as written by fetch_trace.py
  - a wrapper {"trace": {...}, "observations": [...], "scores": [...]}
  - a bare JSON list of observations

Output: plain text by default, or structured JSON with --json. Standard library only.

Tool calls are detected from:
  - observations of type TOOL, or observations (any type) whose name starts with "tool:"
  - Anthropic `tool_use` content blocks in generation output
  - OpenAI-style `tool_calls` in generation output
Tool results that have no matching tool observation are recovered from later generation
inputs (Anthropic `tool_result` blocks, OpenAI `role: tool` messages).

Usage:
  summarize_trace.py <file|-> [--json] [--max-chars N]
"""

import argparse
import json
import sys

DEFAULT_MAX_CHARS = 500
TOOL_PREFIX = "tool:"
ERROR_LEVELS = ("ERROR", "WARNING")


# ---------------------------------------------------------------------------
# Loading and normalising
# ---------------------------------------------------------------------------

def parse_json_maybe(value):
    """Parse a JSON string; return the value unchanged if it is not a JSON string."""
    if isinstance(value, str):
        s = value.strip()
        if s and s[0] in "{[":
            try:
                return json.loads(s)
            except ValueError:
                return value
    return value


def load_trace_data(data):
    """Normalise the accepted input shapes into one trace dict with `observations` and `scores` lists."""
    if isinstance(data, list):
        trace = {"observations": data}
    elif isinstance(data, dict):
        if isinstance(data.get("trace"), dict):
            trace = dict(data["trace"])
            for key in ("observations", "scores"):
                if key in data and key not in trace:
                    trace[key] = data[key]
        else:
            trace = dict(data)
    else:
        raise ValueError("trace JSON must be an object or a list of observations")
    observations = trace.get("observations")
    trace["observations"] = [o for o in observations if isinstance(o, dict)] if isinstance(observations, list) else []
    scores = trace.get("scores")
    trace["scores"] = [s for s in scores if isinstance(s, dict)] if isinstance(scores, list) else []
    return trace


def order_observations(observations):
    """Sort by startTime (ISO 8601 strings sort lexically). Observations without startTime
    keep their file position relative to the previous observation."""
    keyed = []
    last = ""
    for index, obs in enumerate(observations):
        start = obs.get("startTime")
        if isinstance(start, str) and start:
            last = start
        keyed.append((last, index, obs))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in keyed]


def obs_type(obs):
    return str(obs.get("type") or "SPAN").upper()


def is_generation(obs):
    return obs_type(obs) == "GENERATION"


def is_tool_observation(obs):
    name = obs.get("name") or ""
    return obs_type(obs) == "TOOL" or (isinstance(name, str) and name.startswith(TOOL_PREFIX))


def tool_name_from_observation(obs):
    name = obs.get("name") or "unknown"
    return name[len(TOOL_PREFIX):] if name.startswith(TOOL_PREFIX) else name


# ---------------------------------------------------------------------------
# Message and content helpers
# ---------------------------------------------------------------------------

def text_from_content(content):
    """Join the text of a message content value (string, or list of content blocks)."""
    content = parse_json_maybe(content)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in (None, "text", "input_text", "output_text") and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(p for p in parts if p)
    return str(content)


def to_text(value):
    """Render any value as text: strings as is, content blocks joined, everything else as compact JSON."""
    value = parse_json_maybe(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def truncate(text, max_chars):
    if not isinstance(text, str) or not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text
    return "%s... [truncated, %d more chars]" % (text[:max_chars], len(text) - max_chars)


def get_messages(gen_input):
    """Return the list of messages in a generation input, or []."""
    gen_input = parse_json_maybe(gen_input)
    if isinstance(gen_input, list):
        return [m for m in gen_input if isinstance(m, dict)]
    if isinstance(gen_input, dict):
        msgs = parse_json_maybe(gen_input.get("messages"))
        if isinstance(msgs, list):
            return [m for m in msgs if isinstance(m, dict)]
    return []


def get_system(gen_input):
    gen_input = parse_json_maybe(gen_input)
    if isinstance(gen_input, dict):
        system = gen_input.get("system")
        if system:
            return text_from_content(system)
    for msg in get_messages(gen_input):
        if msg.get("role") in ("system", "developer"):
            return text_from_content(msg.get("content"))
    return ""


def normalize_tool(tool):
    """Return {name, description, input_schema} from an Anthropic or OpenAI tool definition."""
    if not isinstance(tool, dict):
        return None
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
    if fn:
        return {
            "name": fn.get("name"),
            "description": fn.get("description"),
            "input_schema": fn.get("parameters"),
        }
    if tool.get("name"):
        return {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "input_schema": tool.get("input_schema", tool.get("parameters")),
        }
    return None


def get_tools(gen_input):
    gen_input = parse_json_maybe(gen_input)
    if not isinstance(gen_input, dict):
        return []
    tools = parse_json_maybe(gen_input.get("tools"))
    if not isinstance(tools, list):
        return []
    return [t for t in (normalize_tool(t) for t in tools) if t]


def parse_assistant_output(output):
    """Return (text, tool_calls) from a generation output.

    Handles: a list of Anthropic content blocks; an Anthropic message dict (`content`);
    an OpenAI message dict (`content` + `tool_calls`); an OpenAI response (`choices`);
    a list holding one message dict; a plain string.
    tool_calls is a list of {id, name, arguments}.
    """
    output = parse_json_maybe(output)
    if output is None:
        return "", []
    if isinstance(output, str):
        return output, []
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                return parse_assistant_output(message)
        if "content" in output or "tool_calls" in output:
            text, calls = parse_assistant_output(output.get("content"))
            calls = list(calls) + _openai_tool_calls(output.get("tool_calls"))
            return text, calls
        if output.get("type") in ("text", "tool_use"):
            return parse_assistant_output([output])
        return to_text(output), []
    if isinstance(output, list):
        if len(output) == 1 and isinstance(output[0], dict) and "role" in output[0]:
            return parse_assistant_output(output[0])
        texts, calls = [], []
        for block in output:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "tool_use":
                    calls.append({
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "arguments": block.get("input"),
                    })
                elif block.get("type") in (None, "text", "output_text") and isinstance(block.get("text"), str):
                    texts.append(block["text"])
        return "\n".join(t for t in texts if t), calls
    return str(output), []


def _openai_tool_calls(tool_calls):
    calls = []
    for tc in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                pass
        calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args})
    return calls


def collect_tool_results(gen_input):
    """Map tool_use_id -> {content, is_error} from tool_result blocks / role=tool messages in a generation input."""
    results = {}
    for msg in get_messages(gen_input):
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            results[msg["tool_call_id"]] = {"content": msg.get("content"), "is_error": False}
        content = parse_json_maybe(msg.get("content"))
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                    results[block["tool_use_id"]] = {
                        "content": block.get("content"),
                        "is_error": bool(block.get("is_error")),
                    }
    return results


def looks_like_error(value):
    """Heuristic: does a tool output look like an error?"""
    value = parse_json_maybe(value)
    if isinstance(value, dict):
        if value.get("is_error") or value.get("isError"):
            return True
        if value.get("error"):
            return True
        status = value.get("status")
        return isinstance(status, str) and status.lower() in ("error", "failed", "failure")
    if isinstance(value, str):
        head = value.strip().lower()[:80]
        return head.startswith(("error", "exception", "traceback", "failed", "fatal")) or "traceback (most recent call last)" in value.lower()
    return False


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _last_user_text(messages):
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = text_from_content(msg.get("content"))
            if text.strip():
                return text
    return ""


def extract_user_message(trace, generations):
    trace_input = parse_json_maybe(trace.get("input"))
    if isinstance(trace_input, str) and trace_input.strip():
        return trace_input
    if isinstance(trace_input, dict):
        text = _last_user_text(get_messages(trace_input))
        if text:
            return text
        for key in ("message", "user_message", "query", "question", "input", "prompt", "text", "content"):
            if isinstance(trace_input.get(key), str) and trace_input[key].strip():
                return trace_input[key]
    elif isinstance(trace_input, list):
        text = _last_user_text([m for m in trace_input if isinstance(m, dict)])
        if text:
            return text
    for gen in generations:
        text = _last_user_text(get_messages(gen.get("input")))
        if text:
            return text
    return to_text(trace_input) if trace_input not in (None, "") else ""


def extract_final_answer(trace, generations):
    output = parse_json_maybe(trace.get("output"))
    if output not in (None, ""):
        if isinstance(output, str):
            return output
        text, _ = parse_assistant_output(output)
        return text or to_text(output)
    for gen in reversed(generations):
        text, _ = parse_assistant_output(gen.get("output"))
        if text.strip():
            return text
    return ""


def format_score(score):
    value = score.get("value")
    if value is None:
        value = score.get("stringValue")
    return {
        "name": score.get("name"),
        "value": value,
        "data_type": score.get("dataType"),
        "source": score.get("source"),
        "comment": score.get("comment"),
        "observation_id": score.get("observationId"),
    }


def _same_args(a, b):
    return parse_json_maybe(a) == parse_json_maybe(b)


def summarize(data, max_chars=DEFAULT_MAX_CHARS):
    """Build the structured summary dict from any accepted trace shape."""
    trace = load_trace_data(data)
    observations = order_observations(trace["observations"])
    generations = [o for o in observations if is_generation(o)]

    # Tool definitions: from the latest generation input that has a `tools` key.
    tools_available, system_prompt = [], ""
    for gen in reversed(generations):
        tools_available = get_tools(gen.get("input"))
        if tools_available:
            break
    if generations:
        system_prompt = get_system(generations[-1].get("input")) or next(
            (get_system(g.get("input")) for g in reversed(generations) if get_system(g.get("input"))), ""
        )

    # Tool results visible in generation inputs, keyed by tool_use_id.
    message_results = {}
    for gen in generations:
        message_results.update(collect_tool_results(gen.get("input")))

    steps, errors = [], []
    unmatched_tool_obs = [o for o in observations if is_tool_observation(o)]
    used_obs_ids = set()
    gen_count = 0

    def cut(value):
        return truncate(to_text(value), max_chars)

    for obs in observations:
        level = str(obs.get("level") or "").upper()
        if level in ERROR_LEVELS:
            errors.append({
                "observation": obs.get("name") or obs.get("id"),
                "type": obs_type(obs),
                "level": level,
                "status_message": truncate(to_text(obs.get("statusMessage")), max_chars),
            })

        if is_generation(obs):
            gen_count += 1
            text, calls = parse_assistant_output(obs.get("output"))
            messages = get_messages(obs.get("input"))
            usage = obs.get("usageDetails") or obs.get("usage")
            steps.append({
                "kind": "generation",
                "index": gen_count,
                "name": obs.get("name"),
                "id": obs.get("id"),
                "start_time": obs.get("startTime"),
                "model": obs.get("model"),
                "usage": usage if isinstance(usage, dict) else None,
                "input_messages": len(messages),
                "tool_calls_requested": [
                    {"id": c.get("id"), "name": c.get("name"), "arguments": cut(c.get("arguments"))}
                    for c in calls
                ],
                "text": truncate(text, max_chars),
            })
            # Pair each requested call with a tool observation (same name and args, in order).
            for call in calls:
                match = None
                for cand in unmatched_tool_obs:
                    if cand.get("id") in used_obs_ids:
                        continue
                    if tool_name_from_observation(cand) == call.get("name") and _same_args(cand.get("input"), call.get("arguments")):
                        match = cand
                        break
                if match is not None:
                    used_obs_ids.add(match.get("id"))
                    continue
                # No tool observation recorded: recover the result from later generation inputs.
                recovered = message_results.get(call.get("id"))
                result = None
                is_error = False
                if recovered:
                    result = cut(text_from_content(recovered["content"]) or recovered["content"])
                    is_error = recovered["is_error"] or looks_like_error(recovered["content"])
                steps.append({
                    "kind": "tool_call",
                    "source": "generation_output",
                    "name": call.get("name"),
                    "arguments": cut(call.get("arguments")),
                    "result": result,
                    "is_error": is_error,
                    "status_message": None,
                    "start_time": obs.get("startTime"),
                })
        elif is_tool_observation(obs):
            output = obs.get("output")
            is_error = level == "ERROR" or looks_like_error(output)
            steps.append({
                "kind": "tool_call",
                "source": "tool_observation",
                "name": tool_name_from_observation(obs),
                "observation_type": obs_type(obs),
                "arguments": cut(obs.get("input")),
                "result": cut(output),
                "is_error": is_error,
                "status_message": truncate(to_text(obs.get("statusMessage")), max_chars) or None,
                "start_time": obs.get("startTime"),
            })

    # Tool results the agent received but that were not flagged as errors on any observation.
    for step in steps:
        if step["kind"] == "tool_call" and step["is_error"] and not any(
            e["observation"] == "tool:" + str(step["name"]) or e["observation"] == step["name"] for e in errors
        ):
            errors.append({
                "observation": "tool:%s" % step["name"],
                "type": "TOOL",
                "level": "ERROR (from output)",
                "status_message": step["status_message"] or step["result"],
            })

    return {
        "trace": {
            "id": trace.get("id"),
            "timestamp": trace.get("timestamp"),
            "name": trace.get("name"),
            "user_id": trace.get("userId"),
            "session_id": trace.get("sessionId"),
            "tags": trace.get("tags") or [],
            "metadata": trace.get("metadata"),
        },
        "user_message": truncate(extract_user_message(trace, generations), max_chars),
        "system_prompt": truncate(system_prompt, max_chars) if system_prompt else "",
        "steps": steps,
        "errors": errors,
        "final_answer": truncate(extract_final_answer(trace, generations), max_chars),
        "scores": [format_score(s) for s in trace["scores"]],
        "tools_available": tools_available,
        "counts": {
            "observations": len(observations),
            "generations": len(generations),
            "tool_calls": sum(1 for s in steps if s["kind"] == "tool_call"),
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _indent(text, prefix="    "):
    return "\n".join(prefix + line for line in str(text).splitlines()) if text else prefix + "(empty)"


def render_text(summary):
    out = []
    t = summary["trace"]
    out.append("TRACE")
    out.append("  id: %s" % (t.get("id") or "(unknown)"))
    out.append("  timestamp: %s" % (t.get("timestamp") or "(unknown)"))
    out.append("  name: %s" % (t.get("name") or "(unknown)"))
    if t.get("user_id"):
        out.append("  user: %s" % t["user_id"])
    if t.get("session_id"):
        out.append("  session: %s" % t["session_id"])
    if t.get("tags"):
        out.append("  tags: %s" % ", ".join(str(x) for x in t["tags"]))
    c = summary["counts"]
    out.append("  observations: %d (generations: %d, tool calls: %d)" % (c["observations"], c["generations"], c["tool_calls"]))

    out.append("")
    out.append("USER MESSAGE")
    out.append(_indent(summary["user_message"] or "(not found in trace)"))

    out.append("")
    out.append("TIMELINE")
    if not summary["steps"]:
        out.append("  (no generations or tool calls found)")
    for step in summary["steps"]:
        if step["kind"] == "generation":
            head = "  [generation %d] %s" % (step["index"], step.get("name") or "")
            out.append(head.rstrip())
            out.append("    model: %s" % (step.get("model") or "(unknown)"))
            if step.get("start_time"):
                out.append("    start: %s" % step["start_time"])
            if step.get("usage"):
                out.append("    usage: %s" % json.dumps(step["usage"], ensure_ascii=False))
            out.append("    input messages: %d" % step["input_messages"])
            if step["tool_calls_requested"]:
                out.append("    requested tool calls:")
                for call in step["tool_calls_requested"]:
                    out.append("      - %s %s" % (call["name"], call["arguments"]))
            else:
                out.append("    requested tool calls: none")
            if step["text"]:
                out.append("    text:")
                out.append(_indent(step["text"], "      "))
        else:
            flag = "  ERROR" if step["is_error"] else ""
            out.append("  [tool call] %s%s" % (step["name"], flag))
            out.append("    args: %s" % step["arguments"])
            if step["result"] is None:
                out.append("    result: (no result recorded in trace)")
            else:
                out.append("    result: %s" % step["result"])
            if step.get("status_message"):
                out.append("    status: %s" % step["status_message"])
            if step.get("source") == "generation_output":
                out.append("    note: no tool observation in trace; call taken from generation output")

    out.append("")
    out.append("ERRORS")
    if summary["errors"]:
        for e in summary["errors"]:
            msg = " - %s" % e["status_message"] if e.get("status_message") else ""
            out.append("  %s %s (%s)%s" % (e["level"], e["observation"], e["type"], msg))
    else:
        out.append("  none")

    out.append("")
    out.append("FINAL ANSWER")
    out.append(_indent(summary["final_answer"] or "(not found in trace)"))

    out.append("")
    out.append("SCORES")
    if summary["scores"]:
        for s in summary["scores"]:
            line = "  %s = %s" % (s["name"], s["value"])
            extras = [x for x in (s.get("data_type"), s.get("source")) if x]
            if extras:
                line += " (%s)" % ", ".join(extras)
            out.append(line)
            if s.get("comment"):
                out.append("    comment: %s" % s["comment"])
    else:
        out.append("  none")

    out.append("")
    out.append("TOOLS AVAILABLE")
    if summary["tools_available"]:
        for tool in summary["tools_available"]:
            out.append("  - %s" % tool["name"])
            out.append("    description: %s" % (tool.get("description") or "(none)"))
            if tool.get("input_schema") is not None:
                out.append("    input_schema: %s" % json.dumps(tool["input_schema"], ensure_ascii=False))
    else:
        out.append("  not recorded in the trace (no `tools` key in any generation input)")

    if summary.get("system_prompt"):
        out.append("")
        out.append("SYSTEM PROMPT (from latest generation input)")
        out.append(_indent(summary["system_prompt"]))
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize a Langfuse trace JSON file as a timeline.")
    parser.add_argument("file", help="trace JSON file, or - for stdin")
    parser.add_argument("--json", action="store_true", help="print structured JSON instead of text")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="truncate tool args, results and message text to N characters "
                             "(default %d, 0 = no limit). Tool descriptions are never truncated." % DEFAULT_MAX_CHARS)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        data = json.loads(raw)
        summary = summarize(data, max_chars=args.max_chars)
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
