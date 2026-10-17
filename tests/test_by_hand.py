"""a run that fixed something says how to see the fix by hand.

the section is read from the run's red proof and the gates that ran the
tests, never from a step's words: the test ids and the exact command the
gate ran. a run with no red proof, or one that stopped, has none.
"""
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.runner import stops, summary

from test_red_order import (FIXED, NL, RED_GATE, RED_TEST, TESTER,
                            TESTER_SAID, WORKER, a_flow, a_repo, folders,
                            read, running)

RED_FIRST = RED_GATE.replace("red-test", "red-first").replace(
    "        red: true" + NL, "")
SHIPPED_RED_FIRST = (
    "    gates:" + NL + "      - gate: red-first" + NL
    + "        command: [\"python\", \"-m\", \"pytest\", \"-q\", \"-p\","
    " \"no:cacheprovider\", \"--junitxml={results}\", \"{test}\"]" + NL
    + "        results: junit" + NL)
HEAD = "## see the fix by hand"


def section(text):
    if HEAD not in text:
        return ""
    return text.split(HEAD + "\n", 1)[1].split("\n## ", 1)[0]


def start_of(place):
    return subprocess.run(["git", "-C", str(place), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_fix_shown_by_the_red_first_replay_names_each_test_and_command(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    start = start_of(place)
    a_flow(tmp_path, "build", TESTER + WORKER + RED_FIRST)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert code == stops.EXIT_OK
    said = section(read(folders()[-1] / "handoff.md"))
    assert ("- red without the fix and green with it, as the red-first gate"
            " on worker.md ran them:") in said
    assert "    python -m pytest -q tests/test_calc.py::test_add" in said
    assert ("- without the fix: the run started at " + start[:7]
            + "; the same command there, with tests/test_calc.py as it is"
            " now, fails") in said


def test_the_shipped_red_first_command_is_shown_as_it_runs_by_hand(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER + SHIPPED_RED_FIRST)
    code, _ = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert code == stops.EXIT_OK
    said = section(read(folders()[-1] / "handoff.md"))
    assert ("    python -m pytest -q -p no:cacheprovider"
            " tests/test_calc.py::test_add") in said
    assert "{results}" not in said
    assert "junitxml" not in said


def test_a_results_flag_and_its_own_value_are_both_dropped():
    cmd = "pytest -q --junitxml {results} {test}"
    assert summary.shown(cmd, "t.py::a", nt=False) == "pytest -q t.py::a"
    assert summary.shown(cmd, "t.py::a", nt=True) == "pytest -q t.py::a"


def test_a_test_id_is_quoted_the_way_the_shell_it_runs_in_reads():
    cmd = "pytest -q {test}"
    odd = "t.py::test_x[a b]"
    assert summary.shown(cmd, odd, nt=False) == "pytest -q 't.py::test_x[a b]'"
    assert summary.shown(cmd, odd, nt=True) == 'pytest -q "t.py::test_x[a b]"'
    assert summary.shown(cmd, "t.py::test_x[1]", nt=True) == \
        "pytest -q t.py::test_x[1]"


def test_a_fix_shown_by_the_red_test_alone_names_the_command_that_ran_red(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, _ = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert code == stops.EXIT_OK
    said = section(read(folders()[-1] / "handoff.md"))
    assert ("- red before the fix, as the red-test gate on tester.md ran"
            " it:") in said
    assert "    python -m pytest -q tests/test_calc.py" in said


def test_a_run_with_no_red_proof_has_no_section(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", WORKER)
    code, _ = running(tmp_path, monkeypatch, place, "build",
                      {"worker.md": ({"calc.py": FIXED}, "done")},
                      "--skip-tests", "hotfix")
    assert code == stops.EXIT_OK
    assert HEAD not in read(folders()[-1] / "handoff.md")


def test_a_run_that_stopped_has_no_section(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER + RED_FIRST)
    code, _ = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "done")})
    assert code != stops.EXIT_OK
    assert HEAD not in read(folders()[-1] / "handoff.md")
