# langfuse-trace-triage

## What it does

A Claude Code skill that reads a Langfuse trace from an LLM agent and works out why the response went wrong. For each trace it names the failure type (wrong tool, wrong arguments, overlapping tool descriptions, a mishandled tool error and others), quotes the evidence from the trace, and suggests a fix, usually a change to a tool description or schema. It also writes a promptfoo test case that replays the failing model step.

The skill is read-only. It never writes to or deletes anything in Langfuse, and trace data goes only to the model running the skill.

## Example

`examples/` holds a real run. The demo agent in `demo-agent/` produced the traces with `llama3.2:3b` on a local Ollama server (CPU only). The reports in `examples/reports/` and the promptfoo tests in `examples/promptfoo/` were written by the skill, run once per trace with `claude -p` on `claude-sonnet-5-5`. They were not edited by hand.

| scenario | what the agent did | skill findings (confidence) | trace | report |
|---|---|---|---|---|
| search_by_title | called `search_books` and answered from the result | none | [json](examples/traces/search_by_title.json) | [report](examples/reports/568e32113f4afef938854f6caee45376.md) |
| shipping_policy | called `get_store_policy` and answered from the result | none | [json](examples/traces/shipping_policy.json) | [report](examples/reports/361515fd899d5188fe2010adc2d56d40.md) |
| undo_delivered_order | "undo my order BK-10234": called `start_return` directly, without `get_order_status` | `description_overlap` (high), `wrong_tool` (medium), `wrong_arguments` (high, low severity), `missing_tool_call` (medium) | [json](examples/traces/undo_delivered_order.json) | [report](examples/reports/52a42ef6a07b1118928148c537b9a39d.md) |
| cancel_bare_number | "cancel order 10571": called `cancel_order` with `"10571"`, got `Invalid order_id: "10571"`, told the user it could not find the order | `wrong_arguments` (medium), `tool_error_mishandled` (medium) | [json](examples/traces/cancel_bare_number.json) | [report](examples/reports/4e30ecd2dd0cd2465c2fafac242f5a8c.md) |
| return_window_from_memory | called `get_store_policy` and answered from the result | none | [json](examples/traces/return_window_from_memory.json) | [report](examples/reports/ae32154e0914ea89e0cf8e77b1e72564.md) |
| cancel_shipped_order | called `cancel_order` on a shipped order, which errored | `tool_error_mishandled` (medium) | [json](examples/traces/cancel_shipped_order.json) | [report](examples/reports/dfd0865869ace75001ee6ce844dcb4d4.md) |
| return_processing_order | called `start_return` on a processing order, which errored | `tool_error_mishandled` (medium), `description_overlap` (medium) | [json](examples/traces/return_processing_order.json) | [report](examples/reports/2f3a8af0320782aaf84fbe2d7e5205c2.md) |
| unneeded_lookup | called `search_books` for a question that needs no tool | `unnecessary_tool_call` (medium) | [json](examples/traces/unneeded_lookup.json) | [report](examples/reports/d16c62931b297a2bcd47834deb76a519.md) |

Two scenarios did not go as designed. `return_window_from_memory` was meant to show a model answering from memory, but the model called `get_store_policy`, so there is no failure. `undo_delivered_order` was meant to show the model cancelling a delivered order; it called `start_return` instead, which succeeded.

An excerpt from the report for `undo_delivered_order`, finding 1:

> `cancel_order`: "Undo an order. Use this when the customer wants to reverse or back out of an order they placed."
>
> `start_return`: "Reverse an order. Use this when the customer wants to undo a purchase and get their money back."

The full report continues with the other findings, a suggested diff for the tool descriptions and a promptfoo test case. The report format is described in [skills/langfuse-trace-triage/reference/output-format.md](skills/langfuse-trace-triage/reference/output-format.md).

These traces and reports belong to `llama3.2:3b`. If you change the model, regenerate the example traces and reports with the new model (see Regenerating the examples). Do not relabel the old ones.

## Install

Two ways to put the skill where Claude Code finds it.

**As a plugin.** Inside Claude Code:

```
/plugin marketplace add hassanhere99/langfuse-trace-triage
/plugin install langfuse-trace-triage@langfuse-trace-triage
```

A plugin skill is invoked as `/langfuse-trace-triage:langfuse-trace-triage`.

**As a copied or symlinked skill.** Copy or symlink `skills/langfuse-trace-triage` into a project's `.claude/skills/` or into `~/.claude/skills/`:

```
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/langfuse-trace-triage" ~/.claude/skills/langfuse-trace-triage
```

The scripts need Python 3.10 or later and no packages.

## Usage

Ask Claude Code in plain words:

- "Why did trace `<trace_id>` go wrong?"
- "Triage the exported trace at `<path>`.json"

The skill saves the report as `<trace_id>.md` and the test as `<trace_id>.yaml` in the directory you name, or the current directory.

You can also run the scripts yourself.

With a trace ID, set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` (default `https://cloud.langfuse.com`; the US region is `https://us.cloud.langfuse.com`), or pass `--env-file`. Values in the env file override the shell.

```
python3 skills/langfuse-trace-triage/scripts/fetch_trace.py <trace_id> -o trace.json
python3 skills/langfuse-trace-triage/scripts/summarize_trace.py trace.json
```

With a local JSON file, skip the fetch:

```
python3 skills/langfuse-trace-triage/scripts/summarize_trace.py path/to/trace.json
```

The repo includes small hand-made trace files for the tests, for example `tests/fixtures/anthropic_tool_use.json`, that you can use to try the script.

`summarize_trace.py` prints a timeline: user message, each generation, each tool call with arguments and result, errors, final answer, scores, and the tool definitions recovered from the generation input. It accepts a trace body, a `{"trace": ..., "observations": ...}` wrapper, or a bare list of observations. Options: `--json` for structured output, `--max-chars N` to change truncation (default 500, 0 for no limit), and `-` to read stdin.

`fetch_trace.py` makes only GET requests. It uses Langfuse's v2 observations API and v3 scores API, and rebuilds a trace object from the observations. The v2 API has no trace-level fields, so `name`, `input`, `output` and `metadata` come from the root observation, and the output carries a `reconstructedFrom` key saying so. It does this because `GET /api/public/traces/{id}` is deprecated and Langfuse Cloud no longer serves it. For self-hosted servers that have no v2 routes, it falls back to that legacy endpoint.

Exit codes of `fetch_trace.py`:

| code | meaning |
|---|---|
| 0 | ok |
| 2 | bad usage (including unreadable `--env-file`, unwritable output, invalid host) |
| 3 | `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` missing |
| 4 | authentication failed (HTTP 401 or 403) |
| 5 | trace not found |
| 6 | network error |
| 7 | other HTTP error |
| 8 | response was not JSON |

## Failure types

| type | meaning |
|---|---|
| `wrong_tool` | called a tool that does not match what the user asked for |
| `wrong_arguments` | right tool, wrong or missing arguments |
| `missing_tool_call` | answered from memory or invented something when a tool was needed |
| `unnecessary_tool_call` | called a tool it did not need |
| `description_overlap` | two tool descriptions are too close for the model to tell apart |
| `tool_error_mishandled` | a tool returned an error and the agent ignored it, retried badly, or claimed success |
| `leaked_internals` | the final answer shows internal IDs, raw JSON or error text |
| `prompt_issue` | a cross-tool problem in the system prompt |
| `model_error` | tools and prompt look fine and the model still got it wrong |
| `inconclusive` | the trace does not contain enough to decide |

Definitions, evidence to look for and usual fix locations are in [skills/langfuse-trace-triage/reference/failure-types.md](skills/langfuse-trace-triage/reference/failure-types.md). The report and test format is in [output-format.md](skills/langfuse-trace-triage/reference/output-format.md) in the same folder.

## Running the demo agent

`demo-agent/` is a customer support agent for an online bookstore, with five tools over fake in-memory data. Two tool descriptions overlap on purpose and one argument is underspecified, so some scenarios fail. It uses the Anthropic API and sends traces to Langfuse. Details are in [demo-agent/README.md](demo-agent/README.md).

Copy `.env.example` to `.env` at the repo root and fill in `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (and `LANGFUSE_HOST` if not the EU cloud). Set `DEMO_MODEL` to an Anthropic model ID, for example `claude-haiku-5-5`. Values in `.env` override the shell.

```
uv venv .venv
uv pip install -r demo-agent/requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r demo-agent/requirements.txt
.venv/bin/python demo-agent/run_demo.py
.venv/bin/python demo-agent/export_traces.py
```

Instead of calling `.venv/bin/python`, you can run `source .venv/bin/activate` first and use `python`.

`run_demo.py` runs eight fixed messages and attaches a score named `expected_tool_check` to each trace. That score is an automated check by `run_demo.py` (did the first tool called match the expected one, by name only). It is not user feedback. `export_traces.py` fetches the traces and writes stripped copies to `examples/traces/`; read them before committing.

`run_demo.py` has not been run yet, so `examples/traces/` and `examples/reports/` do not exist. Running the demo and exporting traces needs the keys above.

Promptfoo test cases: `examples/promptfoo/tools.json` (the demo agent's tool definitions) exists. `examples/promptfoo/promptfooconfig.yaml` is generated together with the example traces and reports and does not exist yet. Once it does, run:

```
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.yaml
```

This needs `ANTHROPIC_API_KEY`, and the latest promptfoo needs Node 22.22 or later.

## Running the tests

```
uv venv .venv
uv pip install -r requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Instead of calling `.venv/bin/python`, you can run `source .venv/bin/activate` first and use `python`.

The tests cover `summarize_trace.py` and `fetch_trace.py` using fixtures in `tests/fixtures/`. They need no network access or API keys. Current result: 25 passed, 1 skipped. The skipped test checks the traces in `examples/traces/`, which do not exist yet.

## Limitations

- Status: only the unit tests and the offline script commands (`summarize_trace.py`, `fetch_trace.py --help` and its missing-keys error, `demo-agent/tools.py --dump-tools`) have been run. `fetch_trace.py` with a real trace ID, `run_demo.py` with keys, `export_traces.py` and `promptfoo eval` have not been run yet.
- The plugin install path (`/plugin marketplace add`, `/plugin install`) has not been tested end to end. `claude plugin validate .` passes.
- Classification is done by the model from one trace, so it can be wrong. Reports state a confidence level for each finding.
- It needs the tool definitions. It recovers them from the generation input in the trace; if they are not there, you have to supply them.
- The skill has not been run on real traces yet. The parser is tested only on hand-made fixtures, in Anthropic and OpenAI-style (`tool_calls`) formats. The demo agent uses the Anthropic format.
- It handles one trace at a time.
- The promptfoo tests replay a single model step, not the whole agent, and model output varies between runs. Run a test before and after the fix.
- `fetch_trace.py` rebuilds the trace from observations, so trace-level fields come from the root observation.
- `summarize_trace.py` pairs requested tool calls with tool observations by name and arguments, so identical repeated calls can be paired wrongly.

## License

MIT. Copyright Muhammad Hassan. See [LICENSE](LICENSE).
