# Demo agent

A small customer support agent for an online bookstore. It exists so the triage skill has real traces to work on. It talks to any OpenAI-compatible chat completions endpoint with tool calling (a local Ollama server by default), and sends one Langfuse trace per user message.

The tools are flawed on purpose. Some scenarios fail, and the traces from those runs are what the skill reads.

## Files

- `tools.py`: fake in-memory books, orders and store policies, the five tool definitions (`TOOLS`, in OpenAI chat completions format; `tools_for(variant)` for the other variants), and `execute(name, args, variant)`, which returns `(result_dict, is_error)`.
- `agent.py`: `run_turn(user_message, scenario_id)`, the tool-use loop (at most 6 model calls) with Langfuse instrumentation.
- `run_demo.py`: runs the fixed scenarios with the variant from `AGENT_VARIANT`, scores each trace, writes `last_run.json`.
- `export_traces.py`: fetches the traces and writes stripped copies to `examples/traces/`.
- `check_langfuse_project.py`: prints the Langfuse host, project name and project ID that the keys in `.env` belong to. It never prints the keys.
- `check_model.py`: sends one tool-calling request to the endpoint in `.env` and checks the reply. It sends nothing to Langfuse.
- `repo_env.py`: loads the repo-root `.env` for the scripts above (see Environment variables).
- `../examples/promptfoo/tools.json`: the tool definitions as JSON, for the promptfoo test cases. Regenerate with `python demo-agent/tools.py --dump-tools > examples/promptfoo/tools.json`.

## Deliberate flaws

1. **Overlapping descriptions.** `cancel_order` is described as "Undo an order" and `start_return` as "Reverse an order". Neither says that cancelling works only on orders that have not shipped, or that returns work only on delivered orders. The server enforces both rules: `cancel_order` on a shipped or delivered order returns an error, and `start_return` on a processing or shipped order returns an error.
2. **Underspecified argument.** The `order_id` argument is described only as "The order ID". The server accepts only the `BK-` form (`BK-10234`) and returns `Invalid order_id: "10234"` for a bare number.

The store policy text (from `get_store_policy`) does state the real rules, so a model that looks it up can answer correctly. The system prompt is short and generic and says nothing about any tool.

## Variants

`AGENT_VARIANT` in `.env` (or the `variant` argument of `run_turn`) selects which version of the tools the agent gets. The default is `flawed`, which is exactly what the committed examples were generated from and must stay reproducible.

| variant | `order_id` description | error messages |
|---|---|---|
| `flawed` (default) | "The order ID" | say what failed |
| `desc_only` | states the format: `BK-` followed by 5 digits, e.g. `BK-10571` | unchanged |
| `errors_only` | unchanged | say what to do next |
| `fixed` | states the format | say what to do next |

The `cancel_order` / `start_return` description overlap (flaw 1) is not fixed in any variant; it is the control of the before/after experiment. Order-ID validation, successful results and the `search_books` matching are identical in all four. Each trace records its variant in `metadata.agent_variant`. `python demo-agent/tools.py --dump-tools --variant fixed` prints a variant's tool definitions. The error messages that `fixed` and `errors_only` change are listed, before and after, in [experiments/results_after.md](../experiments/results_after.md#error-messages-the-fix-changes). The experiment itself is run by `experiments/run_experiment.py`.

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

These are designs, not results. What a given model actually does is in the exported traces. For what `llama3.2:3b` did, see the Example section of the [main README](../README.md#example).

## Environment variables

| variable | required | notes |
|---|---|---|
| `DEMO_MODEL` | yes | model name on the endpoint, for example an Ollama model tag |
| `OPENAI_BASE_URL` | no | defaults to `http://localhost:11434/v1` (Ollama) |
| `OPENAI_API_KEY` | no | defaults to `ollama`, a dummy value that Ollama ignores |
| `AGENT_VARIANT` | no | `flawed` (default), `fixed`, `desc_only` or `errors_only`; see Variants |
| `LANGFUSE_PUBLIC_KEY` | yes | |
| `LANGFUSE_SECRET_KEY` | yes | |
| `LANGFUSE_HOST` | no | defaults to `https://cloud.langfuse.com`; US is `https://us.cloud.langfuse.com` |

`run_demo.py`, `export_traces.py` and `check_langfuse_project.py` load `.env` from the repo root. Copy `.env.example` to `.env` and fill it in. Values in `.env` override variables already set in the shell. Langfuse settings are taken only from `.env`: if `.env` is missing or has no Langfuse keys the scripts stop, and a `LANGFUSE_HOST` exported in the shell is ignored when `.env` does not set one. This keeps keys for another Langfuse project that your shell may export out of the demo. If a required variable is missing, the script names it and exits.

`run_demo.py` prints the Langfuse project name and ID before it sends anything. To check without running the demo:

```
python3 demo-agent/check_langfuse_project.py
```

### Other OpenAI-compatible endpoints

Any endpoint that serves chat completions with tool calling works. For DeepSeek, set `OPENAI_BASE_URL=https://api.deepseek.com`, `OPENAI_API_KEY` to your DeepSeek key, and `DEMO_MODEL` to a model ID from DeepSeek's API docs. This has not been tested.

## Run

```
uv venv .venv
uv pip install -r demo-agent/requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r demo-agent/requirements.txt
.venv/bin/python demo-agent/check_model.py
.venv/bin/python demo-agent/run_demo.py
```

It prints one row per scenario: trace id, whether the check passed, and the tools called. It writes the trace ids to `demo-agent/last_run.json` (scenario ids, trace ids, model and a timestamp; no keys).

Each trace gets a score named `expected_tool_check` with value 1 or 0. This is an automated check written by `run_demo.py`: it compares the first tool the agent called with the expected one in the table above. It is not user feedback, and it looks at the tool name only, not the arguments. A scenario can pass the check and still have a wrong argument.

## Export traces

Langfuse ingests asynchronously, so run the export a minute after the demo:

```
.venv/bin/python demo-agent/export_traces.py                 # every trace in last_run.json
.venv/bin/python demo-agent/export_traces.py TRACE_ID ...    # specific traces
```

Each trace is fetched with `skills/langfuse-trace-triage/scripts/fetch_trace.py`, retried until it has the `expected_tool_check` score and a stable observation count, then written to `examples/traces/<scenario_id>.json`. The export removes `projectId`, `htmlPath`, `userId`, `release`, `version`, score author ids, any `*url` field, and the metadata the SDK adds (`resourceAttributes.*` and `scope.*`, which includes the Langfuse public key). It then refuses to write a file that still contains a string with `pk-lf-`, `sk-lf-` or the project ID. Read the files before committing them. The script cannot know what else your project puts in a trace.

## Trace layout

One trace per user message, named `bookstore-support`, with `scenario_id` in the metadata. Trace input is the user message and trace output is the final answer. Inside: a root span `agent-run`, a generation `llm-call-<n>` per model call, and a TOOL observation `tool:<name>` per tool call. The generation input is `{"messages", "tools"}` exactly as sent to the endpoint, in OpenAI chat completions format, with the system prompt as the first message. The output is the assistant message (`content` and `tool_calls`). A tool error sets level `ERROR` on that observation. It is returned to the model as a `role: tool` message whose content is `{"error": "..."}`; chat completions has no separate error flag.

Reasoning text, if the server returns any (Ollama does for thinking models), is not recorded and not sent back to the model.

## Notes and limitations

- Setup used for the example: Ollama 0.40.17 on a 2019 Intel MacBook Pro, installed with `brew install --cask ollama-app`. On Intel Macs Homebrew has no prebuilt `ollama` formula, so the cask avoids a source build. `ollama ps` showed 100% CPU, so the GPU was not used. A run with the GPU was not done.
- Ollama's default context is 4096 tokens. A long conversation or many tools can be cut off.
- If a script fails with a certificate error on a python.org build of Python, set `SSL_CERT_FILE` to your CA bundle, for example `SSL_CERT_FILE=/etc/ssl/cert.pem` on macOS.
- The example model is small: `llama3.2:3b` on CPU. What it does varies by model and by run, even at temperature 0. The scenarios did not all behave as designed. A second run of `run_demo.py` with the same model at temperature 0 called `cancel_order` in `undo_delivered_order`, where the recorded run called `start_return`. The live promptfoo replay of that trace also called `cancel_order`.
- In the example traces, `llm-call-2` reports fewer input tokens (136 to 201) than `llm-call-1` (about 520), although its prompt is longer. This is probably Ollama counting only tokens outside its prompt cache. It was not verified.
- `llm-rubric` assertions in the promptfoo tests are graded by the same 3B model and are unreliable. For `cancel_shipped_order` the grader's reason read as if the reply met the rubric while the assertion failed. Trust the `javascript` assertions.
- If a thinking model returns a `reasoning` field, promptfoo drops the tool calls from the output (see [output-format.md](../skills/langfuse-trace-triage/reference/output-format.md)).
- The DeepSeek and OpenAI settings in `.env.example` are untested. For OpenAI, `OPENAI_BASE_URL=https://api.openai.com/v1` would be used the same way as the DeepSeek one above. No run with either has been done.
- The skill has been run on eight traces from one demo agent and one model. The parser is also tested on hand-made fixtures in Anthropic and OpenAI-style (`tool_calls`) formats. The demo agent uses the OpenAI chat completions format.
