## New failure types the fixes introduced

One new bad behaviour, and it is not a new skill label. `undo_delivered_order` went from 0/3 failures on `flawed` to 3/3 on `fixed`. On `flawed` the agent called `start_return` first, which is the right action for a delivered order. On `fixed` it called `cancel_order` first, got "Order BK-10234 has been delivered, so it can't be cancelled. It can be returned instead with start_return.", and then told the customer to contact customer service for a return label instead of calling `start_return`. So the new error text was read and then not followed.

**The `order_id` description change causes it, on its own.** Six more runs (3 each, same settings and experiment tag) separate the two fixes:

| Variant | `order_id` description | Error messages | Failures | First tool call |
|---|---|---|---|---|
| flawed | original | original | 0/3 | `start_return` x3 |
| desc_only | format stated | original | **3/3** | `cancel_order` x3 |
| errors_only | original | what to do next | 0/3 | `start_return` x3 |
| fixed | format stated | what to do next | **3/3** | `cancel_order` x3 |

`desc_only` reproduces the regression run for run; `errors_only` does not, and behaves exactly like `flawed`. So the two fixes do not have to combine to cause it. The error-message change cannot influence the first call, because the model has not seen any error yet, and the runs agree. With `desc_only` the error is the original one ("cannot be cancelled because its status is delivered"), and the agent answers that "all sales are final once the order has been shipped" and sends the customer to a returns department; with `fixed` the error points to `start_return` and the agent still does not call it. What is not measured is why a description that only adds the order ID format moves the first call from `start_return` to `cancel_order`; the only difference between `flawed` and `desc_only` is that text. The description fix helps `cancel_bare_number` and hurts `undo_delivered_order`, and with one 3B model and this scenario set there is no way to say whether that trade-off generalises.

Two caveats. These six runs happened after the first 72, on Ollama 0.40.18 instead of 0.40.17 (same model file). A control, `flawed` and `fixed` on this scenario run again on 0.40.18, gave the same tool choices and failure counts (0/3 and 3/3); some answer wording changed, so outputs are not byte-identical across the two versions. And the scenario's expected-label rules were fixed before the runs, but the `desc_only` and `errors_only` traces for it were not triaged.

The skill's own labels on the `fixed` traces add no failure type that is missing from the `flawed` traces (see "Labels by variant").

## What didn't work

- **`cancel_shipped_order` was not fixed by either fix under the rule fixed before the runs.** 3/3 failures on every variant. The `fixed` and `errors_only` answers do pick up the new error text ("once the item has been delivered") but still say "you can initiate a return by contacting our customer service team". A response-level rule, added after I read the answers, scores those two variants 0/3. Which rule is right is a judgement; both are shown above and every answer is in `experiments/runs/index.json`.
- **`errors_only` did not fix `cancel_bare_number`.** The bare number was sent 3/3 times and the order was never cancelled 3/3 times. The model did learn the format from the error ("in the format of BK- followed by 5 digits") but asked the customer for it instead of retrying with `BK-10571`. The description fix removed the problem; the error fix moved the problem to the customer.
- **`desc_only` did not touch the post-error scenarios.** `return_processing_order` stayed at 3/3 failures, `cancel_shipped_order` at 3/3.
- **Neither fix touches `unneeded_lookup`.** 3/3 failures on all four variants, by design: it is not one of the two planned fixes, and `search_books` still cannot match a title and author together (`experiments/discovered_bugs.md`).
- **The `cancel_order` / `start_return` overlap was left as a control, and it did bite.** In `undo_delivered_order` the overlap is still there in every variant, and the `order_id` description change alone (`desc_only`) is enough to tip the first call to `cancel_order`. So a change that looks unrelated to the overlap can change which side of it the model lands on.
- **promptfoo said little about the error fix.** The existing tests replay one model step and replay the recorded (flawed) error text, so they cannot see the error-message change. On the 10 tests the pass count went from 15/30 to 18/30, all from the `cancel_bare_number` test. Four tests stayed at 0/3 on both tool sets, including `return_processing_order`, which the live agent runs fixed 3/3 → 0/3 with the new error text. A one-step replay is a poor test for a fix that works by changing what the tool returns.
- **A 3-run cell at temperature 0 is close to one run.** 22 of 26 cells were identical across the 3 runs. The 0.7 runs differ every time (30 distinct outcomes in 30 runs), yet the failure pattern held: `cancel_bare_number` 5/5 → 0/5, `cancel_shipped_order` 5/5 → 5/5, `return_processing_order` 3/5 → 0/5. One model, one machine, one skill run per trace.
- **The failure checks are regular expressions.** They were validated on the 8 committed traces and a few synthetic answers, and I read the answers for the five scenarios with failures. They are still a proxy for a human reading each answer.
- **Evidence correctness is only partly automated.** The check confirms that every quoted line appears in the trace (no invented quotes were found in the 32 new reports). It cannot catch a wrong conclusion drawn from a true quote. I read the `unneeded_lookup` reports for the false "the store does not list Dune" claim that the committed report made; the new reports do not make it. They say the trace cannot settle whether the book is missing or the search cannot match a combined query. Other reports were not read in full by me.
- **The skill files a clean run under an `inconclusive` heading.** Several reports say "Summary: No failure found" and then list one finding of type `inconclusive`, with high confidence "that the run is correct". `inconclusive` is defined as "not enough data". Scored as written, that is a false positive; scored as a no-failure verdict it is not. Both are shown. This is a format problem in the skill, to be handled in step 6, not in these numbers.
- **The skill could not run Bash beyond its own scripts.** In 25 of the 32 triage runs the skill's closing message mentions a denial (a text match on "denied" or "permission" in the output), usually because it tried to run promptfoo. This matches how the committed reports were made (`claude -p` with only the skill scripts allowed), so no report in this experiment verified its own promptfoo test.
- **The skill repeats a wrong rule in its fixes.** It still suggests describing `start_return` as for orders that "have already shipped or been delivered". The store allows returns only after delivery. The `shipped or delivered` text appears in the suggested fix of 2 of the 8 committed reports, 3 of the 16 new `flawed` reports and 1 of the 16 new `fixed` reports.
- **The skill invented a status.** The committed report for `undo_delivered_order` (`examples/reports/52a42ef6a07b1118928148c537b9a39d.md`) suggests this `cancel_order` description:

  > ```diff
  > + Cancel an order that has not shipped yet (status "processing" or "paid"). Do not use for orders that have shipped or been delivered; use start_return for those. If you do not know the order's status, call get_order_status first.
  > ```

  This store has no `paid` status (`processing`, `shipped`, `delivered`, `cancelled`). The same invented status appears in the suggested fix of 1 of the 16 new `flawed` reports and 1 of the 16 new `fixed` reports; one of them says that the status values are assumptions to replace. The committed report is the one quoted in the article material.
- **The false positive from the committed reports repeats.** `undo_delivered_order` run 1 on `flawed` got `description_overlap` (high) for a run that did the right thing.
