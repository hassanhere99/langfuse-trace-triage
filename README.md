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

`demo-agent/` is a customer support agent for an online bookstore, with five tools over fake in-memory data. Two tool descriptions overlap on purpose and one argument is underspecified, so some scenarios fail. It talks to any OpenAI-compatible chat completions endpoint with tool calling and sends traces to Langfuse. Details are in [demo-agent/README.md](demo-agent/README.md).

### Setup

Copy `.env.example` to `.env` at the repo root. Set the Langfuse keys and host (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`; the default is the EU cloud, the US cloud is `https://us.cloud.langfuse.com`). Then point the agent at a model endpoint with `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `DEMO_MODEL`.

Ollama is the tested default. It needs no paid key:

```
ollama serve
ollama pull llama3.2:3b
```

Ollama 0.40.17 was used, installed with `brew install --cask ollama-app`. On Intel Macs Homebrew has no prebuilt `ollama` formula, so the cask avoids a source build. On a 2019 Intel MacBook Pro, `ollama ps` showed 100% CPU. The `.env.example` block for Ollama is `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama` and `DEMO_MODEL=llama3.2:3b`. `.env.example` also has DeepSeek and OpenAI blocks. They are documented but untested.

To use DeepSeek instead (untested), set these in `.env`:

```
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=<your DeepSeek key>
DEMO_MODEL=<model id from DeepSeek's current model list>
```

OpenAI can be set up the same way with `OPENAI_BASE_URL=https://api.openai.com/v1` (untested).

Langfuse settings are read only from `.env`. `LANGFUSE_*` variables exported in your shell are ignored, so keys for another project cannot leak into the demo. Check which project the keys belong to, and that the model endpoint works:

```
uv venv .venv
uv pip install -r demo-agent/requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r demo-agent/requirements.txt
python3 demo-agent/check_langfuse_project.py
.venv/bin/python demo-agent/check_model.py
```

`check_langfuse_project.py` prints the host, project name and project ID. `check_model.py` sends one request that should produce a tool call. With `llama3.2:3b` it called `get_order_status` and took 15 seconds on the first request.

If a script fails with a certificate error on a python.org build of Python, set `SSL_CERT_FILE` to your CA bundle, for example `SSL_CERT_FILE=/etc/ssl/cert.pem` on macOS.

Instead of calling `.venv/bin/python`, you can run `source .venv/bin/activate` first and use `python`.

### Running it

```
.venv/bin/python demo-agent/run_demo.py
.venv/bin/python demo-agent/export_traces.py
```

`run_demo.py` runs eight fixed messages and attaches a score named `expected_tool_check` to each trace. That score is an automated check by `run_demo.py` (did the first tool called match the expected one, by name only). It is not user feedback. It sends eight new traces to the Langfuse project in `.env`. With `llama3.2:3b` on CPU it took about two minutes. `export_traces.py` fetches the traces and writes stripped copies to `examples/traces/`; read them before committing.

### Regenerating the examples

Do this after changing the model or the tools. In order:

1. `.venv/bin/python demo-agent/run_demo.py` runs the scenarios and writes the trace ids to `demo-agent/last_run.json`.
2. `.venv/bin/python demo-agent/export_traces.py` writes `examples/traces/<scenario>.json`. Wait a minute after step 1, because Langfuse ingests asynchronously.
3. Run the skill once per trace with `claude -p`, from the repo root. For `<scenario>`, use each file name in `examples/traces/`:

```
claude -p "Use the langfuse-trace-triage skill to triage the exported trace at examples/traces/<scenario>.json.
Save the report in examples/reports/ and the promptfoo test case in examples/promptfoo/.
The agent that produced this trace ran against an OpenAI-compatible endpoint configured by the OPENAI_BASE_URL, OPENAI_API_KEY and DEMO_MODEL environment variables." \
  --plugin-dir . \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --permission-mode dontAsk \
  --allowedTools "Skill" "Read" "Glob" "Grep" \
     "Edit(./examples/reports/**)" "Edit(./examples/promptfoo/**)" \
     "Write(./examples/reports/**)" "Write(./examples/promptfoo/**)" \
     "Bash(python3 skills/langfuse-trace-triage/scripts/*)" \
  --model claude-sonnet-5-5
```

`--strict-mcp-config` with an empty MCP config keeps other MCP servers out of the run. Each run took about 40 seconds to 2 minutes and 15 to 19 turns. The skill writes `examples/reports/<trace_id>.md`, `examples/promptfoo/<trace_id>.yaml`, and adds the test to `examples/promptfoo/promptfooconfig.yaml`.

The reports are written for the trace ids in `last_run.json`, so delete the old reports and tests first, or they will sit next to the new ones. Also remove the old entries from the `tests:` list in `examples/promptfoo/promptfooconfig.yaml`, or delete that file so the first skill run recreates it. If the tools changed, regenerate `examples/promptfoo/tools.json` with `python3 demo-agent/tools.py --dump-tools > examples/promptfoo/tools.json`.

### promptfoo tests

```
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.yaml --env-file .env
```

With Ollama this needs no paid key. The tests run against the same endpoint and model as the agent, read from `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `DEMO_MODEL`. The latest promptfoo needs a recent Node. Version 0.126.0 ran on Node 26.13.1. If `node --version` is too old, run `nvm install --lts` and then `nvm exec 26 npx promptfoo@latest ...`. You can set `PROMPTFOO_DISABLE_TELEMETRY=1`. promptfoo exits with code 100 when any test fails.

Result of the recorded run (`llama3.2:3b`, temperature 0, 1 minute 34 seconds): 10 tests, 5 passed, 5 failed, 0 errors. The 10 tests come from 8 traces, because two traces have two tests each. The 5 failures are the tests for the 5 failing traces (`undo_delivered_order`, `cancel_bare_number`, `cancel_shipped_order`, `return_processing_order`, `unneeded_lookup`). They are meant to fail against the tool definitions as recorded in `tools.json`. The 5 passes are the tests for the runs that worked. The run after applying the suggested fixes to `tools.json` was not done, so it is not shown that the fixes make the failing tests pass.

The `llm-rubric` assertions are graded by the same 3B model, and the grading looked unreliable in this run. For `cancel_shipped_order` the grader's reason read as if the reply met the rubric while the assertion failed. Treat the deterministic `javascript` assertions as the result.

## Running the tests

```
uv venv .venv
uv pip install -r requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Instead of calling `.venv/bin/python`, you can run `source .venv/bin/activate` first and use `python`.

The tests cover `summarize_trace.py` and `fetch_trace.py` using fixtures in `tests/fixtures/`. They need no network access or API keys. Current result: 34 passed, 0 skipped. This includes tests that check the traces in `examples/traces/`.

## Limitations

- Status: the unit tests, the script commands, `fetch_trace.py` on real traces, `run_demo.py`, `export_traces.py`, the skill on eight real traces (`claude -p`) and `promptfoo eval` have been run, with `llama3.2:3b` on Ollama. Not done: the promptfoo run after applying the suggested fixes to `tools.json`, a run with DeepSeek or OpenAI (their `.env.example` blocks are untested), and a run with the GPU (Ollama used the CPU only).
- The plugin install path (`/plugin marketplace add`, `/plugin install`) has not been tested end to end. `claude plugin validate .` passes.
- Classification is done by the model from one trace, so it can be wrong. Reports state a confidence level for each finding.
- It needs the tool definitions. It recovers them from the generation input in the trace; if they are not there, you have to supply them.
- The skill has been run on eight traces from one demo agent and one model. The parser is also tested on hand-made fixtures in Anthropic and OpenAI-style (`tool_calls`) formats. The demo agent uses the OpenAI chat completions format.
- It handles one trace at a time.
- The promptfoo tests replay a single model step, not the whole agent, and model output varies between runs. Run a test before and after the fix.
- The example model is small: a 3B model on CPU. What it does varies by model and by run, even at temperature 0. The scenarios in `demo-agent/` did not all behave as designed. A second run of `run_demo.py` with the same model at temperature 0 called `cancel_order` in `undo_delivered_order`, where the recorded run called `start_return`. The live promptfoo replay of that trace also called `cancel_order`.
- Ollama's default context is 4096 tokens. A long conversation or many tools can be cut off.
- In the example traces, `llm-call-2` reports fewer input tokens (136 to 201) than `llm-call-1` (about 520), although its prompt is longer. This is probably Ollama counting only tokens outside its prompt cache. It was not verified.
- If a thinking model returns a `reasoning` field, promptfoo drops the tool calls from the output (see [output-format.md](skills/langfuse-trace-triage/reference/output-format.md)).
- `llm-rubric` assertions graded by a small local model are weak. Trust the `javascript` assertions.
- `fetch_trace.py` rebuilds the trace from observations, so trace-level fields come from the root observation.
- `summarize_trace.py` pairs requested tool calls with tool observations by name and arguments, so identical repeated calls can be paired wrongly.

## License

MIT. Copyright Muhammad Hassan. See [LICENSE](LICENSE).
