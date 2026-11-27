import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


def test_author_credit_and_no_other_name_anywhere_in_tracked_files():
    assert "Muhammad Hassan (@hassanhere99)" in README
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    needle = "hamid" + " ali"  # split so this file does not contain the string itself
    for f in files:
        p = ROOT / f
        if p.is_file() and p.suffix in {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".toml", ""}:
            assert needle not in p.read_text(errors="ignore").lower(), f


def test_langfuse_api_callout():
    assert "2026-11-16" in README
    for needle in ("GET /api/public/traces/{id}", "v2 observations API", "v3 scores API", "self-hosted"):
        assert needle in README.replace("Self-hosted", "self-hosted")


def test_every_relative_link_in_the_readme_exists():
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", README):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        assert (ROOT / target).exists(), target


def test_experiment_table_matches_the_run_index():
    import json
    import aggregate as ag
    runs = json.loads((ROOT / "experiments" / "runs" / "index.json").read_text())["runs"]
    section = README[README.index("## Experiment: do the fixes work?"):README.index("## Install")]
    for sc in ag.SCENARIOS:
        row = next(l for l in section.splitlines() if l.startswith(f"| {sc} |"))
        cells = [c.strip().strip("*") for c in row.strip("|").split("|")][1:]
        want = [ag.fraction(ag.cell(runs, v, sc), "failure") for v in ("flawed", "fixed", "desc_only", "errors_only")]
        assert cells == want, (sc, cells, want)


def test_readme_names_all_four_variants_and_the_untouched_control():
    for v in ("`flawed`", "`fixed`", "`desc_only`", "`errors_only`"):
        assert v in README
    assert "left alone in every variant" in README


def test_readme_determinism_and_location_numbers_match_the_data():
    import json
    import aggregate as ag
    import score_new_reports as sn
    import score_reports as sr
    runs = json.loads((ROOT / "experiments" / "runs" / "index.json").read_text())["runs"]
    baseline = ag.committed_baseline()
    cells, identical, _, _ = ag.determinism(runs, baseline)
    assert f"{len(identical)} of {len(cells)} cells gave 3 identical runs" in README
    gt = sr.load_ground_truth(ROOT / "experiments" / "ground_truth.yaml")
    rows = sn.score_variant("flawed", [r for r in runs if r["variant"] == "flawed"], ROOT / "experiments" / "reports" / "flawed", gt)
    t = sr.totals(rows)
    assert f"right for {t['location_failed'][0]} of {t['location_failed'][1]}" in README
    assert f"named somewhere in the report for {t['location_failed_any'][0]} of {t['location_failed_any'][1]}" in README
