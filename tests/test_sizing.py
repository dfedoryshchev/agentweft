"""a change is sized from what it touches and how much of it is logic, never
from its line count alone: a config key is one line and reaches every caller,
a locale file is hundreds of lines and holds no logic. no model is asked.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.flow import reader
from agentweft.flow import spec as flowspec
from agentweft.mcp import preflight

NL = chr(10)
FUNC = ["def mul(a, b):", "    return a * b"]
# a risk map that ranks nothing these tests touch hot
COLD = "core/engine.py 0.92" + NL + "calc.py 0.1"


def test_a_one_line_config_key_change_sizes_high_blast():
    got = preflight.size([("settings.toml", ["timeout = 30"], 0)])
    assert got["blast"] == "high"
    assert got["size"] == "not small"
    assert any("settings.toml" in w and "config" in w for w in got["why"])


def test_a_four_hundred_line_locale_file_sizes_low_logic():
    lines = ['  "key_' + str(i) + '": "texte ' + str(i) + '",'
             for i in range(400)]
    got = preflight.size([("locales/fr.json", lines, 0)], COLD)
    assert got["logic"] == "low-logic"
    assert got["blast"] == "low"
    assert got["size"] == "small"
    assert got["logic_lines"] == 0


def test_a_small_change_to_cold_code_is_small():
    got = preflight.size([("calc.py", FUNC, 0),
                          ("tests/test_calc.py", ["def test_mul():"] * 30, 0)],
                         COLD)
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
                           0)], COLD)
    assert got["blast"] == "low" and got["size"] == "not small"
    assert got["logic_lines"] == 80


def test_nothing_read_is_not_small():
    got = preflight.size(None)
    assert got["size"] == "not small"
    assert preflight.size_line(got) == ("not sized, so every reviewer runs:"
                                        " the change could not be read")


def test_no_risk_map_is_an_unknown_blast_and_never_small():
    for ranking in (None, "", "nothing a ranking says"):
        got = preflight.size([("calc.py", FUNC, 0)], ranking)
        assert got["blast"] == "unknown", ranking
        assert got["size"] == "not small"
        assert any("no risk map" in w for w in got["why"]), got["why"]
        assert not any("nothing the risk map ranks hot" in w
                       for w in got["why"])
    assert preflight.size_line(preflight.size([("calc.py", FUNC, 0)])) \
        .startswith("not small, unknown blast")


def test_a_hot_file_is_high_blast_with_or_without_a_map_elsewhere():
    got = preflight.size([("cli.py", ['    p.add_argument("--dry-run")'],
                           0)])
    assert got["blast"] == "high"


def test_a_dependency_manifest_is_config_and_high_blast_on_any_line():
    for path in ("requirements.txt", "requirements-dev.txt", "pyproject.toml",
                 "package.json", "package-lock.json", "poetry.lock",
                 "uv.lock", "yarn.lock", "Pipfile", "Pipfile.lock",
                 "Dockerfile", "docker/Dockerfile.dev", "Makefile",
                 "GNUmakefile", "go.sum", "Cargo.lock"):
        assert preflight.file_kind(path) == "config", path
        for added, removed in ((["requests==2.32.0"], 0), ([], 1),
                               (["RUN pip install -r requirements.txt"], 0)):
            got = preflight.size([(path, added, removed)], COLD)
            assert got["blast"] == "high", (path, added, removed)
            assert got["size"] == "not small"
            assert any(path in w and "dependency" in w for w in got["why"])


def test_a_data_text_file_is_still_data():
    assert preflight.file_kind("data/words.txt") == "data"
    assert preflight.file_kind("notes.txt") == "data"


def a_repo(tmp_path, files):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c",
                                                 "user.name=t", "commit", "-q",
                                                 "-m", "start"]):
        subprocess.run(["git", "-C", str(repo)] + args, check=True,
                       capture_output=True)
    return repo


def sized_now(repo, ranking=None):
    import types

    from agentweft.runner import gating, summary

    run = types.SimpleNamespace(tree=summary.Tree(repo), workdir=repo,
                                ranking=ranking)
    return run, lambda: gating.sized_change(run)


def test_a_deleted_file_counts_the_lines_it_took_out_with_its_kind(tmp_path):
    engine = NL.join("x_" + str(i) + " = " + str(i) for i in range(600)) + NL
    repo = a_repo(tmp_path, {"core/engine.py": engine, "calc.py": "x = 1" + NL,
                             "locales/fr.po": "msgid \"a\"" + NL * 50})
    _, size = sized_now(repo, COLD)
    (repo / "core" / "engine.py").unlink()
    got = size()
    assert got["size"] == "not small"
    assert got["logic_lines"] == 600
    assert any("600 logic lines" in w for w in got["why"])


def test_a_deleted_locale_file_holds_no_logic(tmp_path):
    repo = a_repo(tmp_path, {"locales/fr.po": ("msgid \"a\"" + NL) * 50})
    _, size = sized_now(repo, COLD)
    (repo / "locales" / "fr.po").unlink()
    got = size()
    assert got["files"] == 1
    assert got["logic_lines"] == 0


E = chr(0xe9)


@pytest.mark.parametrize("name", ["caf" + E + ".py", "two words.py",
                                  "sub dir/r" + E + "sum" + E + ".py"])
def test_a_new_untracked_file_is_sized_whatever_its_name(tmp_path, name):
    repo = a_repo(tmp_path, {"calc.py": "x = 1" + NL})
    _, size = sized_now(repo, COLD)
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(NL.join("v" + str(i) + " = " + str(i)
                                     for i in range(30)) + NL,
                             encoding="utf-8")
    got = size()
    assert got["files"] == 1, got
    assert got["logic_lines"] == 30


@pytest.mark.parametrize("name", ["caf" + E + ".py", "two words.py"])
def test_a_changed_tracked_file_is_sized_whatever_its_name(tmp_path, name):
    repo = a_repo(tmp_path, {name: "x = 1" + NL})
    _, size = sized_now(repo, COLD)
    (repo / name).write_text("x = 2" + NL + "y = 3" + NL, encoding="utf-8")
    got = size()
    assert got["files"] == 1, got
    assert got["logic_lines"] == 3


def test_a_deleted_dependency_manifest_is_high_blast(tmp_path):
    repo = a_repo(tmp_path, {"requirements.txt": "requests==2.32.0" + NL})
    _, size = sized_now(repo, COLD)
    (repo / "requirements.txt").unlink()
    assert size()["blast"] == "high"


def test_the_shipped_feature_flow_still_runs_two_reviewers_on_a_small_one():
    flow = flowspec.load(reader.read((flowspec_root() / "flow.yaml")
                                     .read_text(encoding="utf-8")))
    assert flow.raw["reviewers"] == 2
    assert flow.raw["small_reviewers"] == 2


def flowspec_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / "flows" / "build-feature"


def a_run(tmp_path, monkeypatch, small=None, ranked=COLD, scored=False):
    """the shipped feature flow on a two-line change; `ranked` is the risk
    map its planner is handed, None for a flow with no map to fetch."""
    import shutil

    import test_wrong_test as wt
    from agentweft.mcp import context

    if small is not None or ranked is not None:
        flows = tmp_path / "flows"
        shutil.copytree(str(wt.FLOWS), str(flows))
        yml = flows / "build-feature" / "flow.yaml"
        text = yml.read_text(encoding="utf-8")
        if small is not None:
            text = text.replace("small_reviewers: 2",
                                "small_reviewers: " + str(small))
        if ranked is not None:
            text = text + "context:" + NL + "  command: [\"ranker\"]" + NL
            monkeypatch.setattr(context, "risk_map",
                                lambda config, where=None: (ranked, ""))
        yml.write_text(text, encoding="utf-8")
        monkeypatch.setattr(wt, "FLOWS", flows)
    answers = {"planner.md": [wt.PLAN], "tester.md": [wt.TESTER],
               "worker.md": [wt.WORKER], "reviewer.md": [wt.OK],
               "reviewer-runs.md": [wt.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wt.RIGHT)],
              "worker.md": [("calc.py", wt.AFTER)]}
    asked, _, code, folder, _ = wt.run_it(tmp_path, monkeypatch, answers,
                                          writes, scored=scored)
    if scored:
        return asked, code, None
    return asked, code, (folder / "handoff.md").read_text(encoding="utf-8")


def test_a_scored_run_says_the_size_and_the_reviewer_it_left_out(
        tmp_path, monkeypatch, capsys):
    asked = a_run(tmp_path, monkeypatch, small=1, scored=True)[0]
    assert "reviewer.md" in asked and "reviewer-runs.md" not in asked
    out = capsys.readouterr().out
    assert "sized the change: small, low blast" in out
    assert ("left out reviewer-runs.md: the change sized small, and the flow"
            " runs 1 reviewer on a small one") in out


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


def test_a_flow_with_no_risk_map_never_leaves_a_reviewer_out(tmp_path,
                                                             monkeypatch):
    asked, code, handoff = a_run(tmp_path, monkeypatch, small=1, ranked=None)
    assert code == 0
    assert asked.count("reviewer-runs.md") == 1
    assert "- size: not small, unknown blast" in handoff
    assert "no risk map" in handoff
    assert "left out" not in handoff


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
