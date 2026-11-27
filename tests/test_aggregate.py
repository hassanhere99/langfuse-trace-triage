import aggregate as ag


def r(variant, scenario, run, failure=False, flaw=False, tools=("t",), text="x"):
    return {"variant": variant, "scenario": scenario, "run": run, "failure": failure, "flaw_triggered": flaw,
            "tools": list(tools), "final_text": text, "elapsed_s": 10.0}


def test_fraction_and_blank_cells():
    runs = [r("flawed", "a", 1, failure=True), r("flawed", "a", 2), r("flawed", "a", 3, failure=True)]
    assert ag.fraction(ag.cell(runs, "flawed", "a"), "failure") == "2/3"
    assert ag.fraction(ag.cell(runs, "fixed", "a"), "failure") == ""


def test_answers_report_the_numbers_for_the_three_questions():
    runs = []
    for run in (1, 2, 3):
        runs += [r("flawed", "cancel_bare_number", run, failure=True, flaw=True),
                 r("desc_only", "cancel_bare_number", run, failure=False, flaw=False),
                 r("errors_only", "cancel_bare_number", run, failure=False, flaw=True)]
        for s in ag.POST_ERROR:
            runs += [r("flawed", s, run, failure=True, flaw=True), r("errors_only", s, run, failure=False, flaw=True),
                     r("desc_only", s, run, failure=True, flaw=True)]
    a1, a2, a3, a4 = ag.answers(runs)
    assert "3/3 → 0/3" in a1 and "bare-number calls 3/3 → 0/3" in a1
    assert "`cancel_shipped_order` 3/3 → 0/3" in a2 and "`return_processing_order` 3/3 → 0/3" in a2
    assert "flawed 3/3 → desc_only 3/3" in a3 and "errors_only` on `cancel_bare_number`: failures 3/3 → 0/3, bare-number calls 3/3 → 3/3" in a3


def test_determinism_detects_identical_and_differing_cells():
    runs = [r("flawed", "search_by_title", i) for i in (1, 2, 3)]
    runs += [r("fixed", "search_by_title", 1, text="a"), r("fixed", "search_by_title", 2, text="b"), r("fixed", "search_by_title", 3, text="a")]
    baseline = {s: {"calls": [{"name": "t"}], "final": "x"} for s in ag.SCENARIOS}
    cells, identical, differing, same = ag.determinism(runs, baseline)
    assert identical == [("flawed", "search_by_title")]
    assert differing == [("fixed", "search_by_title", 2, 3)]
    assert same == ["search_by_title"]


def test_timing_line():
    assert "2 runs" in ag.timing([r("flawed", "a", 1), r("flawed", "a", 2)])
    assert ag.timing([]) == ""


def test_committed_baseline_covers_all_scenarios():
    b = ag.committed_baseline()
    assert set(b) == set(ag.SCENARIOS)
    assert [s for s in ag.SCENARIOS if b[s]["failure"]] == ["cancel_bare_number", "cancel_shipped_order",
                                                            "return_processing_order", "unneeded_lookup"]


def test_first_tools_counts_and_orders():
    rs = [{"first_tool": "cancel_order"}, {"first_tool": "start_return"}, {"first_tool": "cancel_order"}, {"first_tool": None}]
    assert ag.first_tools(rs) == "`cancel_order` x2, `no tool` x1, `start_return` x1"


def _undo(variant, failures):
    return [r(variant, "undo_delivered_order", i + 1, failure=f) | {"first_tool": "cancel_order" if f else "start_return"}
            for i, f in enumerate(failures)]


def test_undo_verdict_names_the_variant_that_reproduces_the_regression():
    base = _undo("flawed", [False] * 3) + _undo("errors_only", [False] * 3) + _undo("fixed", [True] * 3)
    assert "description change alone reproduces" in ag.undo_verdict(base + _undo("desc_only", [True] * 3))
    assert "error-message change alone reproduces" in ag.undo_verdict(
        _undo("flawed", [False] * 3) + _undo("desc_only", [False] * 3) + _undo("errors_only", [True] * 3) + _undo("fixed", [True] * 3))
    assert "Both changes reproduce" in ag.undo_verdict(base[:3] + _undo("desc_only", [True] * 3) + _undo("errors_only", [True] * 3) + _undo("fixed", [True] * 3))
    v = ag.undo_verdict(base + _undo("desc_only", [False] * 3))
    assert "only cause it in combination" in v
    assert "not both run" in ag.undo_verdict(_undo("flawed", [False] * 3) + _undo("fixed", [True] * 3))


def test_undo_table_lists_what_each_variant_changes():
    runs = _undo("flawed", [False] * 3) + [dict(x, flaw_triggered=True) for x in _undo("desc_only", [True] * 3)]
    table = ag.undo_table(runs)
    assert "| desc_only | format stated | original | 3/3 | 3/3 | `cancel_order` x3 |" in table
    assert "| flawed | original | original | 0/3 | 0/3 | `start_return` x3 |" in table
    assert "errors_only" not in table


def test_the_committed_undo_runs_show_which_fix_causes_the_regression():
    import json
    from pathlib import Path
    runs = json.loads((Path(__file__).resolve().parent.parent / "experiments" / "runs" / "index.json").read_text())["runs"]
    by = {v: ag.fraction(ag.cell(runs, v, "undo_delivered_order"), "failure") for v in ("flawed", "desc_only", "errors_only", "fixed")}
    assert by == {"flawed": "0/3", "desc_only": "3/3", "errors_only": "0/3", "fixed": "3/3"}
    assert "description change alone reproduces" in ag.undo_verdict(runs)


# --- skill v1 vs v2 ------------------------------------------------------------------------------------------

def _scored(trace_id, labels, locations, clean=False, ambiguous=False, label_ok=False, location_ok=False, run=1):
    return {"trace_id": trace_id, "scenario": "s", "run": run, "labels": labels, "as_written": labels, "locations": locations,
            "clean": clean, "ambiguous": ambiguous, "label_ok": label_ok, "location_ok": location_ok,
            "expected": "x", "expected_location": "y"}


def test_verdict_changes_separates_primary_changes_from_secondary_only_and_same():
    v1 = [_scored("a", ["wrong_arguments", "tool_error_mishandled"], ["tool_schema"]),
          _scored("b", ["wrong_arguments"], ["tool_schema", "error_message"]),
          _scored("c", ["wrong_arguments"], ["tool_schema"]),
          _scored("d", ["inconclusive"], ["none"])]
    v2 = [_scored("a", ["tool_error_mishandled", "wrong_arguments"], ["tool_schema"]),     # primary label changed
          _scored("b", ["wrong_arguments"], ["tool_schema"]),                              # secondary location dropped only
          _scored("c", ["wrong_arguments"], ["tool_schema"]),                              # same
          _scored("d", ["no_failure"], ["none"])]                                          # primary label changed
    changed, secondary, same = ag.verdict_changes(v1, v2)
    assert [a["trace_id"] for a, _ in changed] == ["a", "d"]
    assert (secondary, same) == (1, 1)


def test_verdict_changes_ignores_traces_without_a_v2_report():
    assert ag.verdict_changes([_scored("a", ["x"], ["none"])], []) == ([], 0, 0)


def test_inconclusive_stats_counts_misuse_and_the_v2_verdict_line(tmp_path):
    (tmp_path / "t1.md").write_text("- Summary: No failure found.\n\n## Findings\n\n### 1. inconclusive (confidence: high)\n")
    (tmp_path / "t2.md").write_text("- Summary: Something is odd.\n\n## Findings\n\n### 1. inconclusive (confidence: low)\n\nData that would settle it: the system prompt.\n")
    (tmp_path / "t3.md").write_text("- Summary: No failure found. fine.\n- Verdict: no_failure\n\n## Suggested fix\n\nfix_location: none\n")
    rows = [{"trace_id": "t1", "clean": True}, {"trace_id": "t2", "clean": False}, {"trace_id": "t3", "clean": True}]
    assert ag.inconclusive_stats(rows, tmp_path) == {"reports": 3, "inconclusive_primary": 2, "misuse": 1, "on_clean": 1,
                                                    "no_data": 1, "explicit_no_failure": 1}


def test_the_v1_numbers_in_results_after_did_not_change():
    import json
    from pathlib import Path
    import score_new_reports as sn
    import score_reports as sr
    root = Path(__file__).resolve().parent.parent
    gt = sr.load_ground_truth(root / "experiments" / "ground_truth.yaml")
    runs = json.loads((root / "experiments" / "runs" / "index.json").read_text())["runs"]
    got = {}
    for v in ("flawed", "fixed"):
        rows = sn.score_variant(v, [r for r in runs if r["variant"] == v], root / "experiments" / "reports" / v, gt)
        t = sr.totals(rows)
        got[v] = (t["label"], t["n"], t["location_failed"], t["location_failed_any"], t["false_pos"], t["sys_prompt_any"])
    assert got == {"flawed": (10, 16, (4, 12), (7, 12), (2, 4), 0), "fixed": (10, 16, (9, 9), (9, 9), (3, 7), 0)}
    text = (root / "experiments" / "results_after.md").read_text()
    assert "| Label accuracy (primary finding) | 10/16 | 11/16 |" in text
