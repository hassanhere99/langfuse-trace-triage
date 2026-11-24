# Demo agent

A small customer support agent for an online bookstore. It exists so the triage skill has real traces to work on. It uses the Anthropic Messages API with tool use, and sends one Langfuse trace per user message.

The tools are flawed on purpose. Some scenarios fail, and the traces from those runs are what the skill reads.

## Files

- `tools.py`: fake in-memory books, orders and store policies, the five tool definitions (`TOOLS`), and `execute(name, args)`, which returns `(result_dict, is_error)`.
- `agent.py`: `run_turn(user_message, scenario_id)`, the tool-use loop (at most 6 model calls) with Langfuse instrumentation.
- `run_demo.py`: runs the fixed scenarios, scores each trace, writes `last_run.json`.
- `export_traces.py`: fetches the traces and writes stripped copies to `examples/traces/`.
- `../examples/promptfoo/tools.json`: the tool definitions as JSON, for the promptfoo test cases. Regenerate with `python demo-agent/tools.py --dump-tools > examples/promptfoo/tools.json`.

## Deliberate flaws

1. **Overlapping descriptions.** `cancel_order` is described as "Undo an order" and `start_return` as "Reverse an order". Neither says that cancelling works only on orders that have not shipped, or that returns work only on delivered orders. The server enforces both rules: `cancel_order` on a shipped or delivered order returns an error, and `start_return` on a processing or shipped order returns an error.
2. **Underspecified argument.** The `order_id` argument is described only as "The order ID". The server accepts only the `BK-` form (`BK-10234`) and returns `Invalid order_id: "10234"` for a bare number.

The store policy text (from `get_store_policy`) does state the real rules, so a model that looks it up can answer correctly. The system prompt is short and generic and says nothing about any tool.

## Scenarios

| id | message | expected first tool | what it is meant to show |
|---|---|---|---|
| search_by_title | stock and price of a title | search_books | a run that should work |
| shipping_policy | shipping time and cost | get_store_policy | a run that should work |
| undo_delivered_order | "undo my order BK-10234" (delivered) | get_order_status | "undo" matches both descriptions, so the model may call `cancel_order` and hit the error |
| cancel_bare_number | "cancel order 10571" | cancel_order | the model passes the bare number and gets an argument error |
| return_window_from_memory | "how many days do I have to return a book" | get_store_policy | the model may answer from memory without calling a tool |
| cancel_shipped_order | cancel BK-10388 (shipped) | cancel_order | the tool errors; the agent has to tell the customer the truth |
| return_processing_order | start a return on BK-10571 (processing) | start_return | the tool errors because the order has not shipped |
| unneeded_lookup | "is Dune a good book for a 14 year old" | none | the model may call `search_books` when no tool is needed |

These are designs, not results. What a given model actually does is in the exported traces.

## Environment variables

| variable | required | notes |
|---|---|---|
| `DEMO_MODEL` | yes | Anthropic model ID, for example `claude-haiku-5-5` |
| `ANTHROPIC_API_KEY` | yes | |
| `LANGFUSE_PUBLIC_KEY` | yes | |
| `LANGFUSE_SECRET_KEY` | yes | |
| `LANGFUSE_HOST` | no | defaults to `https://cloud.langfuse.com`; US is `https://us.cloud.langfuse.com` |

`run_demo.py` and `export_traces.py` load `.env` from the repo root if it exists. Copy `.env.example` to `.env` and fill it in. Values in `.env` override variables already set in the shell. If a required variable is missing, the script names it and exits.

## Run

```
uv venv .venv
uv pip install -r demo-agent/requirements.txt
python demo-agent/run_demo.py
```

It prints one row per scenario: trace id, whether the check passed, and the tools called. It writes the trace ids to `demo-agent/last_run.json` (scenario ids, trace ids, model and a timestamp; no keys).

Each trace gets a score named `expected_tool_check` with value 1 or 0. This is an automated check written by `run_demo.py`: it compares the first tool the agent called with the expected one in the table above. It is not user feedback, and it looks at the tool name only, not the arguments. A scenario can pass the check and still have a wrong argument.

## Export traces

Langfuse ingests asynchronously, so run the export a minute after the demo:

```
python demo-agent/export_traces.py                 # every trace in last_run.json
python demo-agent/export_traces.py TRACE_ID ...    # specific traces
```

Each trace is fetched with `skills/langfuse-trace-triage/scripts/fetch_trace.py`, retried until it has the `expected_tool_check` score and a stable observation count, then written to `examples/traces/<scenario_id>.json`. The export removes `projectId`, `htmlPath`, `userId`, `release`, `version`, score author ids, any `*url` field, and `metadata.resourceAttributes`. Read the files before committing them. The script cannot know what else your project puts in a trace.

## Trace layout

One trace per user message, named `bookstore-support`, with `scenario_id` in the metadata. Trace input is the user message and trace output is the final answer. Inside: a root span `agent-run`, a generation `llm-call-<n>` per model call (input holds the system prompt, messages and full tool definitions), and a TOOL observation `tool:<name>` per tool call. A tool error sets level `ERROR` on that observation and is returned to the model as a `tool_result` with `is_error: true`.

Thinking blocks, if the model returns any, are passed back to the API but left out of the recorded generation input and output.
