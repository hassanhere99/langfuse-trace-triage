# Report format

Write one Markdown report per trace, saved as `<trace_id>.md`, and one promptfoo test file per trace, saved as `<trace_id>.yaml`. Quote evidence exactly as it appears in the trace. Plain language, no hype.

## Report template

````markdown
# Trace <trace_id>

- Timestamp: <trace timestamp>
- User feedback and scores: <score name, value, comment; or "none">
- Summary: <one line: what went wrong>

## Findings

### 1. <failure type> (confidence: high | medium | low)

Evidence:

> <exact tool call, tool result or final-answer text from the trace>

<One or two sentences linking the evidence to the type. If a second finding is related, say how.>

### 2. <failure type> (confidence: ...)

...

## Suggested fix

fix_location: <one or more of tool_description, tool_schema, error_message, system_prompt, none; comma-separated, the main one first>
Location: <tool description | schema | server behaviour | system prompt> of `<tool name>`

Why here: <one sentence applying the fix-location principle>

```diff
- <old text>
+ <new text>
```

## promptfoo test case

<short note on what the test replays and what it asserts>

```yaml
<test case, see below>
```
````

### Report when nothing is wrong

A run with no failure gets the verdict `no_failure`. It has no Findings section (no `### 1.` heading, and no finding of type `inconclusive`), and its `fix_location` is `none`:

````markdown
# Trace <trace_id>

- Timestamp: <trace timestamp>
- User feedback and scores: <score name, value, comment; or "none">
- Summary: No failure found. <one line: what the agent did and why it was right>
- Verdict: no_failure

## Suggested fix

fix_location: none

None. <one line saying what was checked, for example that every figure in the answer comes from a tool result>
````

You may add a short "Checks" or "Notes" section after it (not headed `## Findings`), and a baseline promptfoo test that passes on the recorded run. Anything odd you saw but could not settle, such as a possible problem in an offer the agent made, is a note, or an `inconclusive` report if it needs its own finding.

### Report when the trace cannot settle a suspected failure

Use an `inconclusive` finding only when something looks wrong and the trace cannot show why or whether. Say what looks wrong, and name the data that would settle it:

````markdown
### 1. inconclusive (confidence: low | medium)

Suspected: <what looks wrong, quoted from the trace>

Data that would settle it: <the tool list, the system prompt, the next turn, what the user expected, ...>
````

Its `fix_location` is `none`, and it has no diff and no promptfoo test case. `inconclusive` is never a way to say that a run is correct.

Notes:

- `fix_location` is required in every report and uses only these values: `tool_description` (a tool's description text), `tool_schema` (a parameter's description, enum, pattern or example), `error_message` (the text a tool returns on failure, or other server behaviour), `system_prompt`, or `none` (verdict `no_failure`, or an `inconclusive` finding). The free-text `Location:` line after it says which tool and why.
- Scores that come from a script (an automated check) are not user feedback. Label them by what they are.
- If the result is `inconclusive`, omit the diff and the test case, and name the data that would settle it. If the result is `no_failure`, there is no Findings section.
- Keep diffs minimal. Show only the lines that change, with enough context to find them.

## promptfoo test case

The test reproduces the failing model step. It does not run the whole agent.

- The prompt replays the conversation up to the generation that went wrong. Take it from that generation's `input.messages` in the trace. If the generation input has a separate `input.system`, put it first as a `system` message.
- The tool definitions are the ones in the trace's "Tools available" section, saved as `tools.json` and loaded through the provider config. Keep them as they were at trace time, which means the description you want to fix is still the old text in `tools.json`. Keep the format the trace used (OpenAI `{"type": "function", "function": {...}}` or Anthropic `name`/`input_schema`), and use a provider that accepts that format.
- Prefer deterministic `javascript` assertions on the tool name and arguments. Use an LLM-graded assertion only when the check cannot be written as code, and label it with a `# LLM-graded` comment.
- The assertions describe correct behaviour. They should fail against the tool definitions as recorded and pass once the suggested fix is applied to `tools.json`. If you cannot show that, say which of the two you did not check.

### Provider

The provider is configurable. By default the test runs against the same OpenAI-compatible endpoint and model as the agent under test, read from the environment, so no model name, URL or key is written into the test files:

| variable | meaning |
|---|---|
| `OPENAI_BASE_URL` | the endpoint the agent uses, for example a local Ollama server or a hosted API |
| `OPENAI_API_KEY` | its key (any non-empty value for servers that ignore it, such as Ollama) |
| `DEMO_MODEL` | the model name on that endpoint; use the model the agent ran with, which is in the trace's generation `model` field |

If the agent under test reads differently named variables, use those names in the config instead. If it used a different provider type (for example the Anthropic Messages API), replace the provider block with that promptfoo provider and adapt the assertion helper to its output shape.

### What the assertion receives

With the `openai:chat:<model>` provider (promptfoo 0.126), `output` depends on what the model returned:

| model returned | `output` |
|---|---|
| text only | a string |
| tool calls and no text | an array of tool calls, `[{"id", "type": "function", "function": {"name", "arguments"}}]` |
| tool calls and text | the whole message object, `{"role", "content", "tool_calls"}` |

`function.arguments` is a JSON string, not an object. The provider does not run the tools.

If the server returns a `reasoning` field (thinking models on Ollama do), promptfoo sets `output` to the message text only and drops the tool calls. For a thinking model, switch thinking off for the test, for example `passthrough: { reasoning_effort: none }` in the provider config on servers that support it, and check that a tool call shows up in the output.

Start each `javascript` assertion with this helper, which handles all three shapes:

```js
const msg = typeof output === 'string' ? { content: output, tool_calls: [] }
  : Array.isArray(output) ? { content: '', tool_calls: output } : output;
const calls = (msg.tool_calls || []).map((tc) => {
  let input = {};
  try { input = JSON.parse(tc.function.arguments || '{}'); } catch (e) { input = { _unparsed: tc.function.arguments }; }
  return { name: tc.function.name, input };
});
const text = msg.content || '';
```

Two syntax points: a `javascript` assertion that is a single line is treated as an expression, so `const` fails there; a multi-line value needs an explicit `return`. A `javascript` assertion may return a boolean or an object with `pass`, `score` and `reason`.

### Files

`examples/promptfoo/` (or the directory the user names) holds:

`promptfooconfig.yaml`, shared by all tests:

```yaml
description: Replay failing generations from Langfuse traces
prompts:
  - file://chat.json          # the whole file is one line: {{ messages | dump }}
providers:
  - id: openai:chat:{{ env.DEMO_MODEL }}
    config:
      apiBaseUrl: '{{ env.OPENAI_BASE_URL }}'
      apiKey: '{{ env.OPENAI_API_KEY }}'
      temperature: 0
      max_tokens: 1024
      tools: file://tools.json
defaultTest:
  options:
    provider:                 # grader for llm-rubric assertions: same endpoint
      id: openai:chat:{{ env.DEMO_MODEL }}
      config:
        apiBaseUrl: '{{ env.OPENAI_BASE_URL }}'
        apiKey: '{{ env.OPENAI_API_KEY }}'
        temperature: 0
tests:
  - file://<trace_id>.yaml
```

`tools.json`, copied from the trace in the format it was recorded in, here OpenAI:

```json
[
  {
    "type": "function",
    "function": {
      "name": "cancel_order",
      "description": "Cancel or undo an order.",
      "parameters": {
        "type": "object",
        "properties": { "order_id": { "type": "string" } },
        "required": ["order_id"]
      }
    }
  }
]
```

`<trace_id>.yaml`: a list of tests, loaded by the `tests:` entry above. Paths are relative to the config file. One file can hold several tests if one trace has several findings. Add each new file to the `tests:` list.

### Example

A customer asked to undo an order that had not shipped. The agent called `start_return`, so the test asserts that `cancel_order` is called instead, with the order ID in the right form.

```yaml
- description: "<trace_id>: undo request on an unshipped order should call cancel_order"
  vars:
    messages:
      - role: system
        content: "You are a support agent for an online bookstore. Use the tools to answer."
      - role: user
        content: "Please undo order BK-1001, I ordered it by mistake."
      - role: assistant
        content: ""
        tool_calls:
          - id: call_01
            type: function
            function:
              name: get_order_status
              arguments: '{"order_id": "BK-1001"}'
      - role: tool
        tool_call_id: call_01
        content: '{"order_id": "BK-1001", "status": "processing"}'
  assert:
    - type: javascript
      value: |
        const msg = typeof output === 'string' ? { content: output, tool_calls: [] }
          : Array.isArray(output) ? { content: '', tool_calls: output } : output;
        const calls = (msg.tool_calls || []).map((tc) => {
          let input = {};
          try { input = JSON.parse(tc.function.arguments || '{}'); } catch (e) { input = { _unparsed: tc.function.arguments }; }
          return { name: tc.function.name, input };
        });
        const call = calls[0];
        if (!call) return { pass: false, score: 0, reason: 'no tool call in output' };
        const ok = call.name === 'cancel_order' && call.input.order_id === 'BK-1001';
        return { pass: ok, score: ok ? 1 : 0, reason: JSON.stringify(call) };
    # LLM-graded
    - type: llm-rubric
      value: The reply does not tell the customer that a return has been started.
```

Guidance for writing the assertions:

- Check the tool name and the specific arguments that decide correctness. Do not assert on every argument; unrelated differences should not fail the test.
- For `missing_tool_call`, assert that `calls` is not empty and the first call has the right name.
- For `unnecessary_tool_call`, assert that `calls.length` is 0, or equals the number the correct run would make.
- For `wrong_arguments`, assert the argument value, with a regular expression if the format is the point: `/^BK-\d+$/.test(call.input.order_id)`.
- For `leaked_internals` and `tool_error_mishandled`, the text of the final answer is what matters. If the replay ends with a tool result and the model is expected to reply in text, check `text` with `javascript` (for example, that it does not contain the raw error string) before reaching for `llm-rubric`.
- In OpenAI format, a tool result is a `role: tool` message with a `tool_call_id`, and the preceding assistant message must contain the matching entry in `tool_calls` with the same `id`.

### Running

```
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.yaml --env-file .env
```

`--env-file` loads the endpoint variables from the file and overrides the shell. Use a Node.js version that the installed promptfoo supports. Run it once against the recorded tool definitions (expect a failure) and once after applying the diff to `tools.json` (expect a pass). Model output varies, so a single run is a sample, not a proof.
