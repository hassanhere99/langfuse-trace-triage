"""Bookstore support agent: an Anthropic tool-use loop instrumented with Langfuse.

Trace layout (one trace per user message):
    trace name   bookstore-support, metadata.scenario_id
    agent-run    root span; its input/output become the trace input/output
      llm-call-1 GENERATION, input {"system", "messages", "tools"}, output = text and tool_use blocks
      tool:<name> TOOL observation, input = arguments, output = result; level ERROR on tool errors
      llm-call-2 ...
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import anthropic  # noqa: E402
from langfuse import get_client, propagate_attributes  # noqa: E402

import tools as bookstore  # noqa: E402

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online bookstore. "
    "Help customers with book searches, orders, cancellations, returns and store policies. "
    "Be concise and polite."
)
MAX_ITERATIONS = 6
MAX_TOKENS = 4096
TRACE_NAME = "bookstore-support"


@dataclass
class TurnResult:
    final_text: str
    trace_id: str
    tool_calls: list = field(default_factory=list)  # [{"name", "input", "result", "is_error"}]


def _visible_blocks(content):
    """Text and tool_use blocks as plain dicts (thinking blocks are left out of what we record)."""
    out = []
    for block in content:
        d = block if isinstance(block, dict) else block.model_dump(exclude_none=True)
        if d.get("type") in ("text", "tool_use"):
            out.append(d)
    return out


def _recordable_messages(messages):
    rec = []
    for m in messages:
        if isinstance(m["content"], str):
            rec.append(m)
        else:
            rec.append({"role": m["role"], "content": _visible_blocks(m["content"])})
    return rec


def run_turn(user_message, scenario_id, client=None, model=None):
    """Answer one user message. Returns a TurnResult."""
    model = model or os.environ.get("DEMO_MODEL")
    if not model:
        raise RuntimeError("DEMO_MODEL is not set")
    client = client or anthropic.Anthropic()
    lf = get_client()

    messages = [{"role": "user", "content": user_message}]
    tool_calls = []
    final_text = ""

    with propagate_attributes(trace_name=TRACE_NAME, metadata={"scenario_id": scenario_id}):
        with lf.start_as_current_observation(as_type="span", name="agent-run", input=user_message) as root:
            trace_id = lf.get_current_trace_id() or ""
            for n in range(1, MAX_ITERATIONS + 1):
                with lf.start_as_current_observation(
                    as_type="generation", name=f"llm-call-{n}", model=model,
                    input={"system": SYSTEM_PROMPT, "messages": _recordable_messages(messages), "tools": bookstore.TOOLS},
                ) as gen:
                    try:
                        response = client.messages.create(
                            model=model, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
                            tools=bookstore.TOOLS, messages=messages,
                        )
                    except Exception as exc:
                        gen.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")
                        root.update(output=f"[agent error] {type(exc).__name__}: {exc}", level="ERROR",
                                    status_message=str(exc))
                        raise
                    gen.update(
                        output=_visible_blocks(response.content),
                        usage_details={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
                        metadata={"stop_reason": response.stop_reason},
                    )

                # Pass the full content (including any thinking blocks) back unchanged.
                full_content = [b.model_dump(exclude_none=True) for b in response.content]
                messages.append({"role": "assistant", "content": full_content})
                final_text = "".join(b.text for b in response.content if b.type == "text").strip()

                if response.stop_reason != "tool_use":
                    if not final_text:
                        final_text = f"[no text in response, stop_reason={response.stop_reason}]"
                    break

                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    with lf.start_as_current_observation(
                        as_type="tool", name=f"tool:{block.name}", input=block.input
                    ) as obs:
                        result, is_error = bookstore.execute(block.name, block.input)
                        if is_error:
                            obs.update(output=result, level="ERROR", status_message=result.get("error", "tool error"))
                        else:
                            obs.update(output=result)
                    tool_calls.append({"name": block.name, "input": block.input, "result": result, "is_error": is_error})
                    tr = {"type": "tool_result", "tool_use_id": block.id, "content": _dumps(result)}
                    if is_error:
                        tr["is_error"] = True
                    results.append(tr)
                messages.append({"role": "user", "content": results})
            else:
                final_text = final_text or "[stopped: maximum tool iterations reached]"

            root.update(output=final_text)

    return TurnResult(final_text=final_text, trace_id=trace_id, tool_calls=tool_calls)


def _dumps(obj):
    import json
    return json.dumps(obj)
