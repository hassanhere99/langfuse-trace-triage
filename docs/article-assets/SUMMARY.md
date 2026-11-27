# Summary of numbers

Every number the article could quote, with the file it comes from. `python experiments/make_article_assets.py` regenerates this file from the committed data, so none of these values is typed by hand. Read `experiments/results_after.md` for what the numbers do and do not show.

## Read this first

- **Skill v2.** The `no_failure` / `inconclusive` fix is in commit `38ff5ed`. The same 32 traces were re-triaged with it (`experiments/reports_v2/`) and are compared with v1 below; v1 numbers did not change.
- **The skill change came after the measurements.** The tie-break rule and the explicit `fix_location` field were added in commit `594d363`, after every run, report and score in this experiment. Nothing was re-run with the changed skill.
- **The committed reports in `examples/reports/` were made by an earlier version of the skill**, before the rule "use only the trace being triaged" (commit `9feb2e8`). The new reports in `experiments/reports/` used the skill with that rule and without the step 6 change.
- Failure rates come from regular-expression checks on the tool calls and final answers (`experiments/failure_checks.py`). At temperature 0 most cells are 3 identical runs, so a 3/3 is close to one observation.
- `cancel_shipped_order` depends on which return rule you use; both are listed.
- Ground truth and expected labels are partly judgement; see `experiments/ground_truth.yaml` and `experiments/expected_labels.py`.


## Setup

| Claim | Value | Source |
|---|---|---|
| Model | llama3.2:3b | `experiments/runs/settings.json` |
| Temperature, main runs | 0 | `experiments/runs/settings.json` |
| Seed | none set | `experiments/runs/settings.json` |
| max_tokens | 4096 | `experiments/runs/settings.json` |
| Ollama version | 0.40.17 | `experiments/runs/settings.json` |
| Runs per scenario and variant | 3 | `experiments/runs/settings.json` |
| Traces in the main batch (72 first, then 6 undo_delivered_order runs for desc_only and errors_only) | 78 | `experiments/runs/index.json` |
| Traces in the temperature 0.7 batch | 30 | `experiments/runs_t07/index.json` |
| Temperature, second batch | 0.7 | `experiments/runs_t07/settings.json` |
| Model time for the 78 main runs (s) | 1222 | `experiments/runs/index.json` |
| Slowest single run (s) | 30.6 | `experiments/runs/index.json` |

## Committed reports (before)

| Claim | Value | Source |
|---|---|---|
| Label accuracy | 7/8 | `experiments/results_before.md` |
| Fully correct (label right, no false fact) | 6/8 | `experiments/results_before.md` |
| Fix-location accuracy | 7/8 | `experiments/results_before.md` |
| Reports whose evidence stayed inside the trace | 5/8 | `experiments/results_before.md` |
| False positives on clean-behaviour traces | 1/4 | `experiments/results_before.md` |
| System-prompt edit suggested, failures involving one tool | 0 of 2 | `experiments/results_before.md` |
| System-prompt edit suggested, any report | 0 of 8 | `experiments/results_before.md` |

## Failures out of 3 runs (temperature 0)

| Claim | Value | Source |
|---|---|---|
| search_by_title, committed run (1 run) | 0/1 | `examples/traces/search_by_title.json` |
| search_by_title, flawed | 0/3 | `experiments/runs/index.json` |
| search_by_title, fixed | 0/3 | `experiments/runs/index.json` |
| shipping_policy, committed run (1 run) | 0/1 | `examples/traces/shipping_policy.json` |
| shipping_policy, flawed | 0/3 | `experiments/runs/index.json` |
| shipping_policy, fixed | 0/3 | `experiments/runs/index.json` |
| return_window_from_memory, committed run (1 run) | 0/1 | `examples/traces/return_window_from_memory.json` |
| return_window_from_memory, flawed | 0/3 | `experiments/runs/index.json` |
| return_window_from_memory, fixed | 0/3 | `experiments/runs/index.json` |
| undo_delivered_order, committed run (1 run) | 0/1 | `examples/traces/undo_delivered_order.json` |
| undo_delivered_order, flawed | 0/3 | `experiments/runs/index.json` |
| undo_delivered_order, fixed | 3/3 | `experiments/runs/index.json` |
| undo_delivered_order, desc_only | 3/3 | `experiments/runs/index.json` |
| undo_delivered_order, errors_only | 0/3 | `experiments/runs/index.json` |
| cancel_bare_number, committed run (1 run) | 1/1 | `examples/traces/cancel_bare_number.json` |
| cancel_bare_number, flawed | 3/3 | `experiments/runs/index.json` |
| cancel_bare_number, fixed | 0/3 | `experiments/runs/index.json` |
| cancel_bare_number, desc_only | 0/3 | `experiments/runs/index.json` |
| cancel_bare_number, errors_only | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, committed run (1 run) | 1/1 | `examples/traces/cancel_shipped_order.json` |
| cancel_shipped_order, flawed | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, fixed | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, desc_only | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, errors_only | 3/3 | `experiments/runs/index.json` |
| return_processing_order, committed run (1 run) | 1/1 | `examples/traces/return_processing_order.json` |
| return_processing_order, flawed | 3/3 | `experiments/runs/index.json` |
| return_processing_order, fixed | 0/3 | `experiments/runs/index.json` |
| return_processing_order, desc_only | 3/3 | `experiments/runs/index.json` |
| return_processing_order, errors_only | 0/3 | `experiments/runs/index.json` |
| unneeded_lookup, committed run (1 run) | 1/1 | `examples/traces/unneeded_lookup.json` |
| unneeded_lookup, flawed | 3/3 | `experiments/runs/index.json` |
| unneeded_lookup, fixed | 3/3 | `experiments/runs/index.json` |
| unneeded_lookup, desc_only | 3/3 | `experiments/runs/index.json` |
| unneeded_lookup, errors_only | 3/3 | `experiments/runs/index.json` |

## Planted flaw triggered out of 3 runs

| Claim | Value | Source |
|---|---|---|
| cancel_bare_number, flawed | 3/3 | `experiments/runs/index.json` |
| cancel_bare_number, fixed | 0/3 | `experiments/runs/index.json` |
| cancel_bare_number, desc_only | 0/3 | `experiments/runs/index.json` |
| cancel_bare_number, errors_only | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, flawed | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, fixed | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, desc_only | 3/3 | `experiments/runs/index.json` |
| cancel_shipped_order, errors_only | 3/3 | `experiments/runs/index.json` |
| return_processing_order, flawed | 3/3 | `experiments/runs/index.json` |
| return_processing_order, fixed | 3/3 | `experiments/runs/index.json` |
| return_processing_order, desc_only | 3/3 | `experiments/runs/index.json` |
| return_processing_order, errors_only | 3/3 | `experiments/runs/index.json` |

## cancel_shipped_order, response-level return rule

| Claim | Value | Source |
|---|---|---|
| flawed failures | 3/3 | `experiments/runs/index.json` |
| fixed failures | 0/3 | `experiments/runs/index.json` |
| desc_only failures | 3/3 | `experiments/runs/index.json` |
| errors_only failures | 0/3 | `experiments/runs/index.json` |

## Determinism

| Claim | Value | Source |
|---|---|---|
| Cells with 3 identical runs | 22/26 | `experiments/runs/index.json` |
| Scenarios where the first flawed run matches the committed run exactly | 7/8 | `experiments/runs/index.json` |

## Failures out of 5 runs (temperature 0.7)

| Claim | Value | Source |
|---|---|---|
| cancel_bare_number, flawed | 5/5 | `experiments/runs_t07/index.json` |
| cancel_bare_number, fixed | 0/5 | `experiments/runs_t07/index.json` |
| cancel_shipped_order, flawed | 5/5 | `experiments/runs_t07/index.json` |
| cancel_shipped_order, fixed | 5/5 | `experiments/runs_t07/index.json` |
| return_processing_order, flawed | 3/5 | `experiments/runs_t07/index.json` |
| return_processing_order, fixed | 0/5 | `experiments/runs_t07/index.json` |
| Distinct (tool calls, answer) outcomes across the 30 runs | 30 | `experiments/runs_t07/index.json` |

## promptfoo, existing 10 tests x 3 repeats

| Claim | Value | Source |
|---|---|---|
| flawed tool definitions: passed | 15/30 | `experiments/promptfoo/results.flawed.json` |
| fixed tool definitions: passed | 18/30 | `experiments/promptfoo/results.fixed.json` |

## Skill on new flawed traces (as written)

| Claim | Value | Source |
|---|---|---|
| Traces triaged | 16 | `experiments/results_after.md` |
| Label accuracy | 10/16 | `experiments/results_after.md` |
| Fix-location accuracy | 7/16 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, primary location | 4/12 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, right location named anywhere | 7/12 | `experiments/results_after.md` |
| False positives on expected-clean traces | 2/4 | `experiments/results_after.md` |
| System-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |

## Skill on new flawed traces ('No failure found' read as no_failure)

| Claim | Value | Source |
|---|---|---|
| Traces triaged | 16 | `experiments/results_after.md` |
| Label accuracy | 11/16 | `experiments/results_after.md` |
| Fix-location accuracy | 7/16 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, primary location | 4/12 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, right location named anywhere | 7/12 | `experiments/results_after.md` |
| False positives on expected-clean traces | 1/4 | `experiments/results_after.md` |
| System-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |

## Skill on new fixed traces (as written)

| Claim | Value | Source |
|---|---|---|
| Traces triaged | 16 | `experiments/results_after.md` |
| Label accuracy | 10/16 | `experiments/results_after.md` |
| Fix-location accuracy | 15/16 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, primary location | 9/9 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, right location named anywhere | 9/9 | `experiments/results_after.md` |
| False positives on expected-clean traces | 3/7 | `experiments/results_after.md` |
| System-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |

## Skill on new fixed traces ('No failure found' read as no_failure)

| Claim | Value | Source |
|---|---|---|
| Traces triaged | 16 | `experiments/results_after.md` |
| Label accuracy | 11/16 | `experiments/results_after.md` |
| Fix-location accuracy | 15/16 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, primary location | 9/9 | `experiments/results_after.md` |
| Fix-location accuracy on traces that failed, right location named anywhere | 9/9 | `experiments/results_after.md` |
| False positives on expected-clean traces | 2/7 | `experiments/results_after.md` |
| System-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |

## Fix location on failed flawed traces, by scenario

| Claim | Value | Source |
|---|---|---|
| cancel_bare_number: primary location right (of 3 failed traces) | 0/3 | `experiments/results_after.md` |
| cancel_bare_number: right location named anywhere (of 3 failed traces) | 3/3 | `experiments/results_after.md` |
| cancel_shipped_order: primary location right (of 3 failed traces) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: right location named anywhere (of 3 failed traces) | 0/3 | `experiments/results_after.md` |
| return_processing_order: primary location right (of 3 failed traces) | 1/3 | `experiments/results_after.md` |
| return_processing_order: right location named anywhere (of 3 failed traces) | 1/3 | `experiments/results_after.md` |
| unneeded_lookup: primary location right (of 3 failed traces) | 3/3 | `experiments/results_after.md` |
| unneeded_lookup: right location named anywhere (of 3 failed traces) | 3/3 | `experiments/results_after.md` |

## undo_delivered_order by variant (temperature 0, 3 runs each)

| Claim | Value | Source |
|---|---|---|
| flawed: failures | 0/3 | `experiments/runs/index.json` |
| flawed: first tool call | start_return x3 | `experiments/runs/index.json` |
| desc_only: failures | 3/3 | `experiments/runs/index.json` |
| desc_only: first tool call | cancel_order x3 | `experiments/runs/index.json` |
| errors_only: failures | 0/3 | `experiments/runs/index.json` |
| errors_only: first tool call | start_return x3 | `experiments/runs/index.json` |
| fixed: failures | 3/3 | `experiments/runs/index.json` |
| fixed: first tool call | cancel_order x3 | `experiments/runs/index.json` |

## Ollama update control (undo_delivered_order, 3 runs each)

| Claim | Value | Source |
|---|---|---|
| flawed: failures after the update | 0/3 | `experiments/runs_recheck/index.json` |
| fixed: failures after the update | 3/3 | `experiments/runs_recheck/index.json` |
| Ollama version of the first 72 runs | 0.40.17 | `experiments/runs/settings.json` |
| Ollama version of the 6 extension runs | 0.40.18 | `experiments/runs/settings.json` |
| Ollama version of the control runs | 0.40.18 | `experiments/runs_recheck/settings.json` |

## Skill v1 vs v2 on the same traces: failed flawed traces, by scenario

| Claim | Value | Source |
|---|---|---|
| cancel_bare_number: failure type right (primary), v1 (of 3) | 2/3 | `experiments/results_after.md` |
| cancel_bare_number: failure type right (primary), v2 (of 3) | 1/3 | `experiments/results_after.md` |
| cancel_bare_number: fix location right (primary), v1 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_bare_number: fix location right (primary), v2 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_bare_number: fix location named anywhere, v1 (of 3) | 3/3 | `experiments/results_after.md` |
| cancel_bare_number: fix location named anywhere, v2 (of 3) | 2/3 | `experiments/results_after.md` |
| cancel_shipped_order: failure type right (primary), v1 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: failure type right (primary), v2 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: fix location right (primary), v1 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: fix location right (primary), v2 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: fix location named anywhere, v1 (of 3) | 0/3 | `experiments/results_after.md` |
| cancel_shipped_order: fix location named anywhere, v2 (of 3) | 0/3 | `experiments/results_after.md` |
| return_processing_order: failure type right (primary), v1 (of 3) | 3/3 | `experiments/results_after.md` |
| return_processing_order: failure type right (primary), v2 (of 3) | 1/3 | `experiments/results_after.md` |
| return_processing_order: fix location right (primary), v1 (of 3) | 1/3 | `experiments/results_after.md` |
| return_processing_order: fix location right (primary), v2 (of 3) | 1/3 | `experiments/results_after.md` |
| return_processing_order: fix location named anywhere, v1 (of 3) | 1/3 | `experiments/results_after.md` |
| return_processing_order: fix location named anywhere, v2 (of 3) | 1/3 | `experiments/results_after.md` |
| unneeded_lookup: failure type right (primary), v1 (of 3) | 3/3 | `experiments/results_after.md` |
| unneeded_lookup: failure type right (primary), v2 (of 3) | 2/3 | `experiments/results_after.md` |
| unneeded_lookup: fix location right (primary), v1 (of 3) | 3/3 | `experiments/results_after.md` |
| unneeded_lookup: fix location right (primary), v2 (of 3) | 2/3 | `experiments/results_after.md` |
| unneeded_lookup: fix location named anywhere, v1 (of 3) | 3/3 | `experiments/results_after.md` |
| unneeded_lookup: fix location named anywhere, v2 (of 3) | 2/3 | `experiments/results_after.md` |

## Skill v1 vs v2 on the same traces: totals

| Claim | Value | Source |
|---|---|---|
| failed flawed traces, failure type right (primary), v1 | 8/12 | `experiments/results_after.md` |
| failed flawed traces, fix location right (primary), v1 | 4/12 | `experiments/results_after.md` |
| failed flawed traces, fix location named anywhere, v1 | 7/12 | `experiments/results_after.md` |
| failed flawed traces, failure type right (primary), v2 | 4/12 | `experiments/results_after.md` |
| failed flawed traces, fix location right (primary), v2 | 3/12 | `experiments/results_after.md` |
| failed flawed traces, fix location named anywhere, v2 | 5/12 | `experiments/results_after.md` |
| flawed traces, v1: failure type right (primary), all traces | 10/16 | `experiments/results_after.md` |
| flawed traces, v1: fully correct | 10/16 | `experiments/results_after.md` |
| flawed traces, v1: failed traces reported as no failure | 1/12 | `experiments/results_after.md` |
| flawed traces, v1: false positives on expected-clean traces | 2/4 | `experiments/results_after.md` |
| flawed traces, v1: false positives, unambiguous clean traces only | 1/3 | `experiments/results_after.md` |
| flawed traces, v1: system-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |
| flawed traces, v2: failure type right (primary), all traces | 7/16 | `experiments/results_after.md` |
| flawed traces, v2: fully correct | 7/16 | `experiments/results_after.md` |
| flawed traces, v2: failed traces reported as no failure | 3/12 | `experiments/results_after.md` |
| flawed traces, v2: false positives on expected-clean traces | 1/4 | `experiments/results_after.md` |
| flawed traces, v2: false positives, unambiguous clean traces only | 0/3 | `experiments/results_after.md` |
| flawed traces, v2: system-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |
| fixed traces, v1: failure type right (primary), all traces | 10/16 | `experiments/results_after.md` |
| fixed traces, v1: fully correct | 10/16 | `experiments/results_after.md` |
| fixed traces, v1: failed traces reported as no failure | 3/9 | `experiments/results_after.md` |
| fixed traces, v1: false positives on expected-clean traces | 3/7 | `experiments/results_after.md` |
| fixed traces, v1: false positives, unambiguous clean traces only | 1/4 | `experiments/results_after.md` |
| fixed traces, v1: system-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |
| fixed traces, v2: failure type right (primary), all traces | 12/16 | `experiments/results_after.md` |
| fixed traces, v2: fully correct | 11/16 | `experiments/results_after.md` |
| fixed traces, v2: failed traces reported as no failure | 3/9 | `experiments/results_after.md` |
| fixed traces, v2: false positives on expected-clean traces | 0/7 | `experiments/results_after.md` |
| fixed traces, v2: false positives, unambiguous clean traces only | 0/4 | `experiments/results_after.md` |
| fixed traces, v2: system-prompt edit suggested, any report | 0 of 16 | `experiments/results_after.md` |

## Skill v1 vs v2 on the same traces: use of inconclusive (both variants, 32 reports)

| Claim | Value | Source |
|---|---|---|
| v1: reports | 32 | `experiments/results_after.md` |
| v1: inconclusive as primary label | 5 | `experiments/results_after.md` |
| v1: misuse (inconclusive under a 'No failure found' summary) | 4 | `experiments/results_after.md` |
| v1: inconclusive on an expected-clean trace | 3 | `experiments/results_after.md` |
| v1: explicit no_failure verdict | 0 | `experiments/results_after.md` |
| v2: reports | 32 | `experiments/results_after.md` |
| v2: inconclusive as primary label | 2 | `experiments/results_after.md` |
| v2: misuse (inconclusive under a 'No failure found' summary) | 0 | `experiments/results_after.md` |
| v2: inconclusive on an expected-clean trace | 0 | `experiments/results_after.md` |
| v2: explicit no_failure verdict | 16 | `experiments/results_after.md` |

## Skill v1 vs v2 on the same traces: changes

| Claim | Value | Source |
|---|---|---|
| Traces whose primary finding type or primary fix location changed | 15/32 | `experiments/results_after.md` |
| Traces that differ only in secondary findings or later locations | 2 | `experiments/results_after.md` |
| Traces with the same findings and locations | 15 | `experiments/results_after.md` |

## Error messages the fix changes

| Claim | Value | Source |
|---|---|---|
| Error sites changed | 8 | `experiments/error_changes.py` |
| Concrete messages changed | 12 | `experiments/error_changes.py` |
| Error sites not changed | 1 | `experiments/error_changes.py` |

## Tests

| Claim | Value | Source |
|---|---|---|
| Tests collected by pytest | 201 | `tests/` |

## Files in this folder

| File | What it is | Source |
|---|---|---|
| `timeline_excerpt.txt` | The compact timeline of the `cancel_bare_number` trace, from the user message to the final answer | `examples/traces/cancel_bare_number.json`, summarised by `skills/langfuse-trace-triage/scripts/summarize_trace.py` |
| `report_cancel_bare_number.md` | The committed report, copied byte for byte | `examples/reports/4e30ecd2dd0cd2465c2fafac242f5a8c.md` |
| `fix_order_id.diff` | `demo-agent/tools.py` in git commit `56433b6`: the `AGENT_VARIANT` switch and the `order_id` format fix | `git diff 56433b6~1 56433b6 -- demo-agent/tools.py` |
| `fix_start_return_error.diff` | `demo-agent/tools.py` in git commit `16ff7a9`: every error message that now says what to do next, including the `start_return` one | `git diff 16ff7a9~1 16ff7a9 -- demo-agent/tools.py` |
| `promptfoo_cancel_bare_number.yaml` | The generated test for this trace, copied byte for byte | `examples/promptfoo/4e30ecd2dd0cd2465c2fafac242f5a8c.yaml` |
