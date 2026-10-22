"""a change is sized from what it touches and how much of it is logic, never
from its line count alone: a config key is one line and reaches every caller,
a locale file is hundreds of lines and holds no logic. no model is asked.
"""
import sys

sys.path.insert(0, ".")
from agentweft.flow import reader
from agentweft.flow import spec as flowspec
from agentweft.mcp import preflight

NL = chr(10)
FUNC = ["def mul(a, b):", "    return a * b"]


def test_a_one_line_config_key_change_sizes_high_blast():
    got = preflight.size([("settings.toml", ["timeout = 30"], 0)])
    assert got["blast"] == "high"
    assert got["size"] == "not small"
    assert any("settings.toml" in w and "config" in w for w in got["why"])


def test_a_four_hundred_line_locale_file_sizes_low_logic():
    lines = ['  "key_' + str(i) + '": "texte ' + str(i) + '",'
             for i in range(400)]
    got = preflight.size([("locales/fr.json", lines, 0)])
    assert got["logic"] == "low-logic"
    assert got["blast"] == "low"
    assert got["size"] == "small"
    assert got["logic_lines"] == 0


def test_a_small_change_to_cold_code_is_small():
    got = preflight.size([("calc.py", FUNC, 0),
                          ("tests/test_calc.py", ["def test_mul():"] * 30, 0)])
    assert (got["size"], got["blast"], got["logic_lines"]) == ("small", "low",
                                                               2)


def test_a_file_the_risk_map_ranks_hot_is_high_blast_however_small():
    got = preflight.size([("core/engine.py", ["x = 1"], 0)],
                         "core/engine.py 0.92" + NL + "calc.py 0.1")
    assert got["blast"] == "high"
    assert got["size"] == "not small"
    assert any("core/engine.py" in w and "0.92" in w for w in got["why"])


def test_a_new_command_line_flag_is_high_blast():
    got = preflight.size([("cli.py", ['    p.add_argument("--dry-run")'], 0)])
    assert got["blast"] == "high"


def test_many_logic_lines_are_not_small():
    got = preflight.size([("calc.py", ["x = " + str(i) for i in range(80)],
                           0)])
    assert got["blast"] == "low" and got["size"] == "not small"
    assert got["logic_lines"] == 80


def test_nothing_read_is_not_small():
    got = preflight.size(None)
    assert got["size"] == "not small"
    assert preflight.size_line(got) == ("not sized, so every reviewer runs:"
                                        " the change could not be read")


def test_the_shipped_feature_flow_still_runs_two_reviewers_on_a_small_one():
    flow = flowspec.load(reader.read((flowspec_root() / "flow.yaml")
                                     .read_text(encoding="utf-8")))
    assert flow.raw["reviewers"] == 2
    assert flow.raw["small_reviewers"] == 2


def flowspec_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "flows" / "build-feature"


def a_run(tmp_path, monkeypatch, small=None):
    import shutil

    import test_wrong_test as wt

    if small is not None:
        flows = tmp_path / "flows"
        shutil.copytree(str(wt.FLOWS), str(flows))
        yml = flows / "build-feature" / "flow.yaml"
        yml.write_text(yml.read_text(encoding="utf-8").replace(
            "small_reviewers: 2", "small_reviewers: " + str(small)),
            encoding="utf-8")
        monkeypatch.setattr(wt, "FLOWS", flows)
    answers = {"planner.md": [wt.PLAN], "tester.md": [wt.TESTER],
               "worker.md": [wt.WORKER], "reviewer.md": [wt.OK],
               "reviewer-runs.md": [wt.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wt.RIGHT)],
              "worker.md": [("calc.py", wt.AFTER)]}
    asked, _, code, folder, _ = wt.run_it(tmp_path, monkeypatch, answers,
                                          writes)
    return asked, code, (folder / "handoff.md").read_text(encoding="utf-8")


def test_the_shipped_flow_sizes_the_change_and_still_runs_both_reviewers(
        tmp_path, monkeypatch):
    asked, code, handoff = a_run(tmp_path, monkeypatch)
    assert code == 0
    assert asked.count("reviewer-runs.md") == 1
    assert "- size: small, low blast, logic: 2 logic lines in 1 code" \
        " file, nothing the risk map ranks hot" in handoff
    assert "left out" not in handoff


def test_a_flow_that_runs_one_reviewer_on_a_small_change_leaves_one_out(
        tmp_path, monkeypatch):
    asked, code, handoff = a_run(tmp_path, monkeypatch, small=1)
    assert code == 0
    assert "reviewer.md" in asked and "reviewer-runs.md" not in asked
    assert ("- left out reviewer-runs.md: the change sized small, and the"
            " flow runs 1 reviewer on a small one") in handoff


def test_small_reviewers_is_held_to_the_reviewers_the_flow_runs():
    base = {"name": "f", "steps": [
        {"role": "worker", "prompt": "w.md"},
        {"role": "reviewer", "prompt": "a.md", "lens": "one"},
        {"role": "reviewer", "prompt": "b.md", "lens": "two"}],
        "reviewers": 2}
    assert not [b for b in flowspec.check(dict(base, small_reviewers=1))
                if "small_reviewers" in b]
    for bad in (0, 3, "one", True):
        assert [b for b in flowspec.check(dict(base, small_reviewers=bad))
                if "small_reviewers" in b], bad
