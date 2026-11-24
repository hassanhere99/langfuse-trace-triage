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

Notes:

- Scores that come from a script (an automated check) are not user feedback. Label them by what they are.
- If the result is `inconclusive`, omit the diff and the test case, and list the data needed instead.
- Keep diffs minimal. Show only the lines that change, with enough context to find them.

## promptfoo test case

The test reproduces the failing model step. It does not run the whole agent.

- The prompt replays the conversation up to the generation that went wrong. Take it from that generation's `input.messages` in the trace, and put `input.system` first as a `system` message.
- The tool definitions are the ones in the trace's "Tools available" section, saved as `tools.json` and loaded through the provider config. Keep them as they were at trace time, which means the description you want to fix is still the old text in `tools.json`.
- Prefer deterministic `javascript` assertions on the tool name and arguments. Use an LLM-graded assertion only when the check cannot be written as code, and label it with a `# LLM-graded` comment.
- The assertions describe correct behaviour. They should fail against the tool definitions as recorded and pass once the suggested fix is applied to `tools.json`. If you cannot show that, say which of the two you did not check.

### What the assertion receives

With the `anthropic:messages:<model>` provider, `output` is a string. Text blocks come first, and each `tool_use` block is `JSON.stringify` of the whole block on its own line, with blocks separated by a blank line:

```
I will look that up.

{"type":"tool_use","id":"toolu_01...","name":"start_return","input":{"order_id":"BK-1001"}}
```

The provider does not run the tools. The assertions below pick out lines that start with `{"type":"tool_use"` and parse them. A text-only reply has no such line.

Two syntax points checked against promptfoo 0.118: a `javascript` assertion that is a single line is treated as an expression, so `const` fails there; a multi-line value needs an explicit `return`. A `javascript` assertion may return a boolean or an object with `pass`, `score` and `reason`.

### Files

`examples/promptfoo/` (or the directory the user names) holds:

`promptfooconfig.yaml`, shared by all tests:

```yaml
description: Replay failing generations from Langfuse traces
prompts:
  - file://chat.json          # the whole file is one line: {{ messages | dump }}
providers:
  - id: anthropic:messages:claude-sonnet-5   # use the model the agent ran with
    config:
      temperature: 0
      max_tokens: 1024
      tools: file://tools.json
tests:
  - file://<trace_id>.yaml
```

`tools.json`, in Anthropic format (`name`, `description`, `input_schema`), copied from the trace:

```json
[
  {
    "name": "cancel_order",
    "description": "Cancel or undo an order.",
    "input_schema": {
      "type": "object",
      "properties": { "order_id": { "type": "string" } },
      "required": ["order_id"]
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
        content:
          - type: tool_use
            id: toolu_01
            name: get_order_status
            input: { order_id: "BK-1001" }
      - role: user
        content:
          - type: tool_result
            tool_use_id: toolu_01
            content: '{"order_id": "BK-1001", "status": "processing"}'
  assert:
    - type: javascript
      value: |
        const calls = output
          .split('\n')
          .filter((line) => line.startsWith('{"type":"tool_use"'))
          .map((line) => JSON.parse(line));
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
- For `missing_tool_call`, assert that a `tool_use` line exists and has the right name.
- For `unnecessary_tool_call`, assert that no line starts with `{"type":"tool_use"`, or that `calls.length` equals the number the correct run would make.
- For `wrong_arguments`, assert the argument value, with a regular expression if the format is the point: `/^BK-\d{4}$/.test(call.input.order_id)`.
- For `leaked_internals` and `tool_error_mishandled`, the text of the final answer is what matters. If the replay ends with a tool result and the model is expected to reply in text, `output` is that text; check it with `javascript` (for example, that it does not contain the raw error string) before reaching for `llm-rubric`.
- Messages containing tool results use `role: user` with `tool_result` blocks, and the preceding assistant message must contain the matching `tool_use` block with the same `id`.

### Running

```
npx promptfoo@latest eval -c examples/promptfoo/promptfooconfig.yaml
```

Needs `ANTHROPIC_API_KEY` in the environment, and a Node.js version that the installed promptfoo supports. Run it once against the recorded tool definitions (expect a failure) and once after applying the diff to `tools.json` (expect a pass). Model output varies, so a single run is a sample, not a proof.
