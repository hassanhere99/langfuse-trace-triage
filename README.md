# langfuse-trace-triage

[![tests](https://github.com/hassanhere99/langfuse-trace-triage/actions/workflows/tests.yml/badge.svg)](https://github.com/hassanhere99/langfuse-trace-triage/actions/workflows/tests.yml)

## What it does

A Claude Code skill that reads a Langfuse trace from an LLM agent and works out why the response went wrong. For each trace it names the failure type (wrong tool, wrong arguments, overlapping tool descriptions, a mishandled tool error and others), quotes the evidence from the trace, and suggests a fix, usually a change to a tool description or schema. It also writes a promptfoo test case that replays the failing model step.

The skill is read-only. It never writes to or deletes anything in Langfuse, and trace data goes only to the model running the skill.

## Quick start

To try the skill on a committed example trace you need only Claude Code, no Langfuse account and no model endpoint:

```
git clone https://github.com/hassanhere99/langfuse-trace-triage && cd langfuse-trace-triage
claude --plugin-dir .
# then ask: Triage the exported trace at examples/traces/cancel_bare_number.json
```

The skill writes `<trace_id>.md` and `<trace_id>.yaml` in the current directory.

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

The reports were written before the promptfoo run, so the five that have a failing test say it was not run or not checked. The results are in the promptfoo section below.

The reports predate the rule that the skill uses only the trace being triaged. The `cancel_bare_number` report used other trace files in `examples/traces/` as evidence for the `BK-` order ID format.

These traces and reports belong to `llama3.2:3b`. If you change the model, regenerate the example traces and reports with the new model (see Regenerating the examples). Do not relabel the old ones.

## Experiment: do the fixes work?

The example above shows the skill finding problems. [`experiments/`](experiments/) measures whether fixing them helps. The same eight scenarios were run on `llama3.2:3b` (temperature 0, no seed, 3 runs each; `desc_only` and `errors_only` on five of the eight) against four versions of the demo agent's tools, selected with `AGENT_VARIANT` in `.env`:

| variant | what it changes |
|---|---|
| `flawed` | nothing: the tools the examples were made with |
| `desc_only` | the `order_id` description states the format (`BK-` followed by 5 digits, e.g. `BK-10571`) |
| `errors_only` | error messages say what to do next (8 error sites, 12 messages; the full list is in `results_after.md`) |
| `fixed` | both |

The `cancel_order` / `start_return` description overlap is left alone in every variant, as a control. Failures out of 3 runs (a run fails by the rules in [`experiments/failure_checks.py`](experiments/failure_checks.py)); blank means not run:

| scenario | flawed | fixed | desc_only | errors_only |
|---|---|---|---|---|
| search_by_title | 0/3 | 0/3 | | |
| shipping_policy | 0/3 | 0/3 | | |
| return_window_from_memory | 0/3 | 0/3 | | |
| undo_delivered_order | 0/3 | **3/3** | **3/3** | 0/3 |
| cancel_bare_number | 3/3 | 0/3 | 0/3 | 3/3 |
| cancel_shipped_order | 3/3 | 3/3 | 3/3 | 3/3 |
| return_processing_order | 3/3 | 0/3 | 3/3 | 0/3 |
| unneeded_lookup | 3/3 | 3/3 | 3/3 | 3/3 |

What this shows, for this model and these scenarios:

- The description fix removes the wrong-format call (`cancel_bare_number` 3/3 → 0/3) and does nothing for the failures after an error.
- The error fix changes what the agent does after an error (`return_processing_order` 3/3 → 0/3), but did not fix the bare-number case: the model learned the format from the error and asked the customer for it instead of retrying.
- `cancel_shipped_order` depends on how strictly you read the answers: 3/3 failures on every variant under the rule fixed before the runs, 0/3 on `fixed` and `errors_only` under a looser rule added after reading them. Both are in the results.
- **`fixed` made `undo_delivered_order` worse** (0/3 → 3/3), and the `order_id` description change alone does it: `desc_only` also fails 3/3 (first call `cancel_order` every time) while `errors_only` is 0/3 like `flawed` (first call `start_return`). The same description text that fixes `cancel_bare_number` tips this scenario onto the wrong side of the `cancel_order` / `start_return` overlap that was left unfixed.
- At temperature 0, 22 of 26 cells gave 3 identical runs, so 3 runs is close to 1. A separate 5-run batch at temperature 0.7 gave the same pattern for the three scenarios it covered.
- The skill's reports were scored against a hand-written ground truth. On the 8 committed reports: label right 7/8, fully correct 6/8 (one report states a false fact), 1 false positive on 4 clean-behaviour traces, and no report suggested a system-prompt edit. On 32 new traces it was right on 10/16 (`flawed`) and 10/16 (`fixed`) as written. On the `flawed` traces that actually failed, its first-named fix location was right for 4 of 12 and the right location was named somewhere in the report for 7 of 12 (per scenario in `results_after.md`). The reports say a clean run is "inconclusive" often enough that the table also shows the count with that read as no failure.

Read [`experiments/results_before.md`](experiments/results_before.md) (the committed reports vs the ground truth), [`experiments/results_after.md`](experiments/results_after.md) (runs, promptfoo, new triage, temperature 0.7 and a "what didn't work" section), [`experiments/discovered_bugs.md`](experiments/discovered_bugs.md) (a `search_books` bug found while scoring, left unfixed) and [`docs/article-assets/SUMMARY.md`](docs/article-assets/SUMMARY.md) (every number above with its source file).

Two things to know before quoting any of it. The committed reports in `examples/reports/` were made by an earlier version of the skill, before the rule "use only the trace being triaged"; the new reports use the skill with that rule. And the skill gained a root-cause tie-break rule and an explicit `fix_location` field after all measurements (commit `594d363`); nothing was re-run with it.

## Install

Two ways to put the skill where Claude Code finds it.

**As a plugin.** Inside Claude Code:

```
/plugin marketplace add hassanhere99/langfuse-trace-triage
/plugin install langfuse-trace-triage@langfuse-trace-triage
```

Tested on 2026-11-25 with Claude Code 2.1.84: installing from GitHub with `claude plugin marketplace add` and `claude plugin install`, then running the installed skill on an example trace.

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

> **Langfuse Cloud API change.** Langfuse Cloud retired `GET /api/public/traces/{id}` on 2026-11-16, so a fetch script that used it stops working there. `fetch_trace.py` instead reads the trace's observations from the v2 observations API (`GET /api/public/v2/observations?traceId=...`) and its scores from the v3 scores API (`GET /api/public/v3/scores`), and rebuilds the trace object from them. The v2 API has no trace-level fields, so `name`, `input`, `output` and `metadata` come from the root observation, and the output carries a `reconstructedFrom` key saying so. Self-hosted Langfuse v3 servers have no v2 routes; for those, the script falls back to the legacy `GET /api/public/traces/{id}` endpoint. It makes only GET requests.

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

The `.env.example` block for Ollama is `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama` and `DEMO_MODEL=llama3.2:3b`. `.env.example` also has DeepSeek and OpenAI blocks, which are untested. Install details and other notes are in [demo-agent/README.md](demo-agent/README.md#notes-and-limitations).

Langfuse settings are read only from `.env`. `LANGFUSE_*` variables exported in your shell are ignored, so keys for another project cannot leak into the demo. Check which project the keys belong to, and that the model endpoint works:

```
uv venv .venv
uv pip install -r demo-agent/requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r demo-agent/requirements.txt
python3 demo-agent/check_langfuse_project.py
.venv/bin/python demo-agent/check_model.py
```

`check_langfuse_project.py` prints the host, project name and project ID. `check_model.py` sends one request that should produce a tool call. With `llama3.2:3b` it called `get_order_status` and took 15 seconds on the first request.

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

Result of the recorded run (`llama3.2:3b`, temperature 0, 1 minute 34 seconds): 10 tests, 5 passed, 5 failed, 0 errors. The 10 tests come from 8 traces, because two traces have two tests each. The 5 failures are the tests for the 5 failing traces (`undo_delivered_order`, `cancel_bare_number`, `cancel_shipped_order`, `return_processing_order`, `unneeded_lookup`). They are meant to fail against the tool definitions as recorded in `tools.json`. The 5 passes are the tests for the runs that worked.

### Fix loop: the same tests against the suggested fixes

`examples/promptfoo/promptfooconfig.fixed.yaml` runs the same tests against `examples/promptfoo/tools.fixed.json`. That file is `tools.json` with the description and schema fixes from the reports applied. It was built by hand from the reports' diffs. Where reports overlapped, the fixes were merged. Fixes that change server behaviour, such as better error messages, cannot be expressed in `tools.json` and were not applied. One merge decision: `start_return` is limited to delivered orders, where one report said "shipped or delivered".

```
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.yaml --env-file .env
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.fixed.yaml --env-file .env
```

Both runs used `llama3.2:3b`, temperature 0 and `--repeat 3`, so 10 tests x 3 = 30 results each. Passes per test, out of 3:

| trace | test | before | after |
|---|---|---|---|
| `search_by_title` | stock and price: `search_books` with title | 3/3 | 3/3 |
| `shipping_policy` | shipping: `get_store_policy` with shipping | 3/3 | 3/3 |
| `shipping_policy` | final answer has time and cost | 3/3 | 3/3 |
| `undo_delivered_order` | starts with `get_order_status` | 0/3 | 0/3 |
| `cancel_bare_number` | bare number cancel uses the `BK-` ID | 0/3 | 3/3 |
| `return_window_from_memory` | returns question: `get_store_policy` with returns | 3/3 | 3/3 |
| `return_window_from_memory` | final answer gives 30 days | 3/3 | 3/3 |
| `cancel_shipped_order` | after failed cancel, no return offered | 0/3 | 0/3 |
| `return_processing_order` | after failed `start_return`, offer `cancel_order`, no invented policy | 0/3 | 0/3 |
| `unneeded_lookup` | question about a 14-year-old answered without search | 0/3 | 0/3 |

Overall: before 15 passed, 15 failed; after 18 passed, 12 failed; 0 errors in both.

Only the failing test for `cancel_bare_number` now passes. The `BK-` instruction in the `order_id` description made the model add the prefix every time. The other four still fail:

- `undo_delivered_order`: the model still calls a state-changing tool without `get_order_status` first (`start_return` in the before run, `cancel_order` in the after run). This choice also varied between earlier runs with the original `tools.json`.
- `cancel_shipped_order`: after the error the model still offers a return shipping label.
- `return_processing_order`: the model still says returns are possible for "shipped or delivered" orders and does not offer `cancel_order`.
- `unneeded_lookup`: the model still calls `search_books` for a question about a book's age suitability.

The 5 passing control tests still pass. The three repeats were identical at temperature 0, so they add little. No assertions were changed. With this small model, descriptions alone fixed 1 of 5 failures. The reports' server-side fixes (error messages, rejecting the wrong order status) could not be applied in `tools.json`. Whether they or a different model would fix the other four was not tested.

## Running the tests

```
uv venv .venv
uv pip install -r requirements.txt -r demo-agent/requirements.txt    # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r demo-agent/requirements.txt
.venv/bin/python -m pytest
```

Instead of calling `.venv/bin/python`, you can run `source .venv/bin/activate` first and use `python`.

The tests need no network access, API keys or model. Current result: 188 passed, 0 skipped (the original 34 plus 154 added for the variants, the experiment tooling and the docs). They cover:

- **The skill's scripts (34 tests, the original suite).** `summarize_trace.py`: Anthropic-style and OpenAI-style tool calls, tool errors with and without an `ERROR` level, several generations ordered by time, missing or null fields, odd inputs that must not crash, truncation, the command line, and a pass over every committed trace in `examples/traces/`. `fetch_trace.py`: rebuilding a trace from paged v2 observations plus scores against a local fake server, the not-found, other-HTTP-error and network-error exit codes, missing keys and the `.env` parser.
- **The demo agent's variants.** `flawed` tool definitions equal `examples/promptfoo/tools.json`; `fixed`, `desc_only` and `errors_only` each differ from `flawed` in exactly the claimed places (definitions diffed path by path, every error message compared); the control descriptions are unchanged; successful results and order-ID validation are identical across variants; the agent passes the variant, temperature and trace metadata through.
- **The experiment tooling.** The report parser and scorers (labels, fix locations, evidence quotes, false positives, system-prompt edits), the ground-truth file against the committed traces, the per-run failure checks against the eight committed traces, the expected-label rules, the run plans (78 main runs, 30 at temperature 0.7, 6 control runs), the export step and the triage driver's selection and blinding.
- **The skill's text.** The tie-break rule and the `fix_location` field are present, and the article assets are byte-identical copies with sourced numbers.

CI runs the same command on Python 3.10 and 3.12.

## Limitations

- It works on one trace at a time, and classification is done by the model from that trace, so it can be wrong. Reports state a confidence level for each finding.
- It needs the tool definitions. It recovers them from the generation input in the trace; if they are not there, you have to supply them.
- The promptfoo tests replay a single model step, not the whole agent, and model output varies between runs. Run a test before and after the fix. In the fix loop above, description changes alone fixed 1 of 5 failing tests with the small example model.
- `fetch_trace.py` rebuilds the trace from observations, so trace-level fields come from the root observation.
- The experiment is one small model, one machine and mostly temperature 0, where repeated runs are nearly identical. Failure checks are regular expressions, and the ground truth is partly judgement. See `experiments/results_after.md` before quoting any number.
- `summarize_trace.py` pairs requested tool calls with tool observations by name and arguments, so identical repeated calls can be paired wrongly.

More notes on the demo agent and the example model are in [demo-agent/README.md](demo-agent/README.md#notes-and-limitations).

## License

MIT. Copyright Muhammad Hassan. See [LICENSE](LICENSE).

Author: Muhammad Hassan (@hassanhere99).
