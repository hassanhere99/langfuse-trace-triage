"""Bookstore support agent: an OpenAI-compatible chat completions tool loop, instrumented with Langfuse.

Works with any OpenAI-compatible endpoint. The endpoint, key and model come only from the
environment (OPENAI_BASE_URL, OPENAI_API_KEY, DEMO_MODEL), normally set in the repo-root .env.

Trace layout (one trace per user message):
    trace name   bookstore-support, metadata.scenario_id
    agent-run    root span; its input/output become the trace input/output
      llm-call-1 GENERATION, input {"messages", "tools"} exactly as sent (system prompt is the first
                 message), output = the assistant message {"role", "content", "tool_calls"}
      tool:<name> TOOL observation, input = arguments, output = result; level ERROR on tool errors
      llm-call-2 ...
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openai  # noqa: E402
from langfuse import get_client, propagate_attributes  # noqa: E402

import tools as bookstore  # noqa: E402

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online bookstore. "
    "Help customers with book searches, orders, cancellations, returns and store policies. "
    "Be concise and polite."
)
MAX_ITERATIONS = 6
MAX_TOKENS = 4096
TEMPERATURE = 0
TRACE_NAME = "bookstore-support"
ENDPOINT_ENV = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "DEMO_MODEL")
REQUEST_TIMEOUT = 900  # seconds; a local model on CPU can be slow


@dataclass
class TurnResult:
    final_text: str
    trace_id: str
    tool_calls: list = field(default_factory=list)  # [{"name", "input", "result", "is_error"}]


def make_client():
    missing = [k for k in ENDPOINT_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    return openai.OpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=REQUEST_TIMEOUT,
        max_retries=0,
    )


def _assistant_message(message):
    """The assistant message as a plain dict: role, content and tool_calls only.

    Reasoning text that some servers return for thinking models (a `reasoning` or
    `reasoning_content` field) is left out of what we record and of what we send back.
    """
    out = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        out["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]
    return out


def _parse_arguments(raw):
    """Tool arguments arrive as a JSON string. Returns (dict, error_or_None)."""
    if isinstance(raw, dict):
        return raw, None
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        return {"_raw": raw}, f"Tool arguments are not valid JSON: {exc}"
    if not isinstance(args, dict):
        return {"_raw": raw}, "Tool arguments must be a JSON object"
    return args, None


def run_turn(user_message, scenario_id, client=None, model=None):
    """Answer one user message. Returns a TurnResult."""
    model = model or os.environ.get("DEMO_MODEL")
    if not model:
        raise RuntimeError("DEMO_MODEL is not set")
    client = client or make_client()
    lf = get_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_message}]
    tool_calls = []
    final_text = ""

    with propagate_attributes(trace_name=TRACE_NAME, metadata={"scenario_id": scenario_id}):
        with lf.start_as_current_observation(as_type="span", name="agent-run", input=user_message) as root:
            trace_id = lf.get_current_trace_id() or ""
            for n in range(1, MAX_ITERATIONS + 1):
                with lf.start_as_current_observation(
                    as_type="generation", name=f"llm-call-{n}", model=model,
                    model_parameters={"temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
                    input={"messages": [dict(m) for m in messages], "tools": bookstore.TOOLS},
                ) as gen:
                    try:
                        response = client.chat.completions.create(
                            model=model, messages=messages, tools=bookstore.TOOLS,
                            temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
                        )
                    except Exception as exc:
                        gen.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                        root.update(output=f"[agent error] {type(exc).__name__}: {exc}", level="ERROR",
                                    status_message=str(exc))
                        raise
                    choice = response.choices[0]
                    assistant = _assistant_message(choice.message)
                    usage = {}
                    if response.usage is not None:
                        usage = {"input": response.usage.prompt_tokens or 0,
                                 "output": response.usage.completion_tokens or 0}
                    gen.update(output=assistant, usage_details=usage,
                               metadata={"finish_reason": choice.finish_reason})

                messages.append(assistant)
                final_text = (assistant["content"] or "").strip()

                if not assistant.get("tool_calls"):
                    if not final_text:
                        final_text = f"[no text in response, finish_reason={choice.finish_reason}]"
                    break

                for tc in assistant["tool_calls"]:
                    name = tc["function"]["name"]
                    args, parse_error = _parse_arguments(tc["function"]["arguments"])
                    with lf.start_as_current_observation(as_type="tool", name=f"tool:{name}", input=args) as obs:
                        if parse_error:
                            result, is_error = {"error": parse_error}, True
                        else:
                            result, is_error = bookstore.execute(name, args)
                        if is_error:
                            obs.update(output=result, level="ERROR", status_message=result.get("error", "tool error"))
                        else:
                            obs.update(output=result)
                    tool_calls.append({"name": name, "input": args, "result": result, "is_error": is_error})
                    # Chat completions has no error flag on tool results; the error is in the content.
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)})
            else:
                final_text = final_text or "[stopped: maximum tool iterations reached]"

            root.update(output=final_text)

    return TurnResult(final_text=final_text, trace_id=trace_id, tool_calls=tool_calls)
