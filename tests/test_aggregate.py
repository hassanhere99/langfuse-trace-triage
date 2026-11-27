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
