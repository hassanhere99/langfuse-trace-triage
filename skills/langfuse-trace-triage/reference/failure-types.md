# Failure types

Use one of these types per finding. A trace can have several findings. Examples use a bookstore support agent.

When a symptom (wrong tool, wrong arguments…) and a root cause (overlapping descriptions, missing format…) both fit, label the root cause, and put the symptom in the evidence.

For each type: what it is, what in the trace shows it, where the fix usually goes, and how to tell it from its neighbours.

## wrong_tool

**Definition.** The agent called a tool that does not match what the user asked for.

**Evidence.** A tool call whose name does not fit the user message. Example: the user wrote "undo my order" and the agent called `start_return`, a tool for items already delivered, on an order that had not shipped.

**Usual fix.** The description of the tool that was wrongly chosen, and of the one that should have been chosen, to say when each applies and when it does not.

**Telling it apart.**
- If the two descriptions are close enough that either reading is reasonable, report `description_overlap` as well, and treat it as the cause. `wrong_tool` is then the symptom.
- If the descriptions are clear and distinct and the model still picked the wrong one, it is `model_error`.

## wrong_arguments

**Definition.** The right tool was called with wrong or missing arguments.

**Evidence.** The tool call arguments disagree with the user message or with earlier tool results: a date in the wrong year, an order ID copied from a different turn, a field left out, a value in the wrong format (`1001` where the tool needs `BK-1001`). Often followed by a tool error or an empty result.

**Usual fix.** The argument's schema: its `description`, `enum`, `pattern` or an example value. If the server can accept both forms, normalising the value in the tool is also a fix.

**Telling it apart.**
- If the schema never said what format to use, the cause is an underspecified schema; say so in the finding.
- If the schema states the format and the model ignored it, that is `model_error`.
- If the error text came back and the agent then made it worse, add `tool_error_mishandled`.

## missing_tool_call

**Definition.** The agent answered from memory or invented something when it should have called a tool.

**Evidence.** A final answer containing specifics (order status, a price, a policy) with no tool call anywhere in the trace that could have produced them.

**Usual fix.** The description of the tool that should have been used, so that it says it is the source for that information. Only if several tools are affected, a line in the system prompt.

**Telling it apart.**
- Not `missing_tool_call` if no available tool could have supplied the answer. That is a gap in the tool set; report it as a finding of type `inconclusive` or a note, not as a model failure.
- Check "Tools available" before using this type.

## unnecessary_tool_call

**Definition.** The agent called a tool it did not need.

**Evidence.** A tool call whose result is unused, repeats an earlier call with the same arguments, or answers a question the user did not ask.

**Usual fix.** The tool's description, to say when not to use it. Low severity unless the call has side effects.

**Telling it apart.**
- A read-only extra call is usually cheap. A repeated call that changes state (a second cancellation) is worse; call that out.
- A retry after an error is not unnecessary. Judge it under `tool_error_mishandled`.

## description_overlap

**Definition.** Two or more tool descriptions are close enough that the model cannot reliably tell them apart.

**Evidence.** In "Tools available", descriptions that share the same verbs and nouns ("cancel or undo an order" and "start a return to undo an order"), and a trace where the agent picked one of them for a request the other was meant for. Quote both descriptions.

**Usual fix.** Rewrite both descriptions with a distinguishing condition (order not yet shipped versus already delivered) and a "do not use for" sentence. Change both, not one.

**Telling it apart.**
- This type explains a `wrong_tool` finding; it does not replace it. Report both when both are present.
- One trace showing a wrong pick is weak evidence of overlap on its own. If the descriptions are plainly distinct, do not use this type.

## tool_error_mishandled

**Definition.** A tool returned an error and the agent ignored it, retried badly, or told the user the action worked.

**Evidence.** A tool observation with level ERROR, `is_error` true, or error text in its result, followed by a final answer that claims success, or by a repeat of the same failing call with unchanged arguments.

**Usual fix.** Server behaviour first: return an error that says what to change ("order_id must look like BK-1234"). Then the tool description, if it should tell the model what to do on failure. A system prompt rule about errors is only justified if it applies to every tool.

**Telling it apart.**
- If the error text was vague, the cause is the tool's error message, and the fix goes there.
- If the first call failed because of bad arguments, also report `wrong_arguments`.

## leaked_internals

**Definition.** The final answer shows internal IDs, raw JSON or error text to the user.

**Evidence.** The final answer contains a database ID, a stack trace, a JSON object, or a message such as `KeyError`. Quote the part of the answer and the tool result it came from.

**Usual fix.** Server behaviour (do not return internal fields or raw errors to the model) or the tool description (say which fields are for the user). Use a system prompt line only if the leak happens across several tools.

**Telling it apart.**
- A customer-facing reference number the user already knows (an order number) is not an internal ID.

## prompt_issue

**Definition.** A real cross-tool problem in the system prompt: a rule that conflicts with another, a missing global behaviour, or an instruction that pushes the agent the wrong way across several tools.

**Evidence.** The system prompt text, quoted, together with behaviour in this trace that follows from it. Ideally the same effect shows in more than one tool.

**Usual fix.** The system prompt.

**Telling it apart.**
- Use this type only when the problem is cross-tool. If the rule belongs to one tool, the fix goes in that tool and the type is one of the tool-level types above.
- If the system prompt is not in the trace, you cannot establish this type. Say `inconclusive` and ask for the prompt.

## model_error

**Definition.** The tools and prompt look fine and the model still got it wrong.

**Evidence.** Clear, distinct descriptions and a clear schema, an unambiguous user message, and a wrong action anyway. Quote the description or schema text that was clear.

**Usual fix.** None in the tool or prompt text is warranted. Options are a different model or a regression test to track it. The promptfoo test still has value.

**Telling it apart.**
- This is the last type to reach for. Re-read the descriptions as the model would, with no knowledge of the code, before using it. Most failures that look like model errors are underspecified text.

## inconclusive

**Definition.** Something looks wrong, and the trace cannot show why or whether. It is for a suspected failure that the trace cannot settle. It is not for a run where nothing is wrong: that is `no_failure`.

**Evidence.** A suspicion you can state (an odd answer, a user complaint, an action that may or may not have been right) plus what blocks the decision: missing tool definitions, no system prompt, truncated or null generation input, or a user complaint that cannot be matched to anything in the run.

**Fix.** None proposed. The finding must name the data that would settle it: the tool list, the system prompt, the next turn of the conversation, or what the user expected.

**Telling it apart.**
- Nothing looks wrong and the answer matches the tool results: `no_failure`, not `inconclusive`. High confidence "that the run is correct" is a `no_failure` verdict.
- You cannot name a suspected failure and the data that would settle it: it is not `inconclusive`.

## no_failure (a verdict, not a finding type)

A run where the agent did what the user asked and the answer matches the tool results has no findings. The report states the verdict `no_failure`, has no Findings section, and says `fix_location: none`. Do not list a finding to say that the run is fine.

## Confidence

- **high**: the evidence is in the trace and there is only one reasonable reading. You can quote the call, the result and the text that caused it.
- **medium**: the evidence is in the trace but another reading fits. Say what the other reading is.
- **low**: the finding rests on inference, such as a likely cause with no direct evidence. Prefer `inconclusive` over a low-confidence finding unless the user asked for hypotheses.

Do not raise confidence because a fix sounds plausible. Confidence is about the diagnosis.
