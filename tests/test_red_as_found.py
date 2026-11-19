"""a step's suite gate is failed only by tests that were green when the run
started.

a test red when the run started (a red tree the run was handed) is "red as
found": the command gate that runs the suite lists it and passes on it. a
test the step turned red, or one the run added, still fails the gate.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates
from agentweft.runner import stops

from test_red_order import a_flow
from test_test_edits import (COUNT, COUNTED, ID, NL, SORTED, TESTER,
                             TESTER_SAID, WORKER, WORKER_SAID, WRONG, a_place,
                             folders, module, read, running)

SUITE = (WORKER + "    gates:" + NL + "      - gate: command" + NL
         + "        command: [\"python\", \"-m\", \"pytest\", \"-q\"]" + NL)
UNSORTED = "def report(names):" + NL + "    return list(names)" + NL + NL \
    + NL + "def count(names):" + NL + "    return len(names)" + NL
NO_COUNT = SORTED + NL + NL + "def count(names):" + NL + "    return 0" + NL


def does_of(product):
    return {"tester.md": ({"tests/test_report.py": module(WRONG, COUNT)},
                          TESTER_SAID),
            "worker.md": ({"report.py": product}, WORKER_SAID)}


@pytest.mark.parametrize("commits", [False, True])
def test_a_test_red_when_the_run_started_is_red_as_found_and_passes(
        tmp_path, monkeypatch, commits):
    place = a_place(tmp_path / "repo", baseline=WRONG)
    a_flow(tmp_path, "build", TESTER + SUITE)
    code, called = running(tmp_path, monkeypatch, place, does_of(COUNTED),
                           commits)
    assert called == ["tester.md", "worker.md"]
    assert code == 0
    gated = read(folders()[-1] / "gates.md")
    assert "PASS command - exit 1, red as found: " + ID + " (each red when" \
        " the run started)" in gated


def test_a_test_the_step_turned_red_still_fails_the_gate(tmp_path,
                                                         monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + SUITE)
    does = does_of(UNSORTED)
    does["tester.md"] = ({"tests/test_report.py": module(
        "def test_alphabetical():" + NL
        + "    assert listed(['b', 'a']) == ['a', 'b']" + NL, COUNT)},
        TESTER_SAID)
    code, called = running(tmp_path, monkeypatch, place, does, False)
    assert called == ["tester.md", "worker.md", "worker.md"]
    assert code != 0
    gated = read(folders()[-1] / "gates.md")
    assert "FAIL command - exit 1" in gated
    assert "red as found" not in gated


def test_a_red_beside_one_red_as_found_still_fails_the_gate(tmp_path,
                                                            monkeypatch):
    place = a_place(tmp_path / "repo", baseline=WRONG)
    a_flow(tmp_path, "build", TESTER + SUITE)
    code, called = running(tmp_path, monkeypatch, place, does_of(NO_COUNT),
                           False)
    assert called == ["tester.md", "worker.md", "worker.md"]
    assert code != 0
    gated = read(folders()[-1] / "gates.md")
    assert "FAIL command - exit 1" in gated
    assert "red as found" not in gated


SUMMARY = ("..F.F" + NL + "=" * 20 + " short test summary info " + "=" * 20
           + NL + "FAILED tests/test_a.py::test_one - assert 1 == 2" + NL
           + "ERROR tests/test_b.py::test_two[x] - NameError" + NL)


def said(text, code=1):
    g = gates.build({"gate": "command", "command": [
        sys.executable, "-c", "import sys; sys.stdout.buffer.write("
        + repr(text) + ".encode('utf-8')); sys.exit(" + str(code) + ")"]})
    return g.run("anything")


def test_the_gate_reads_every_red_its_suite_named():
    r = said(SUMMARY + "1 failed, 3 passed, 1 error in 0.10s" + NL)
    assert not r
    assert r.failing == ["tests/test_a.py::test_one",
                         "tests/test_b.py::test_two[x]"]


@pytest.mark.parametrize("text", [
    "", "exit with nothing named" + NL,
    SUMMARY + "2 failed, 3 passed, 1 error in 0.10s" + NL,
    SUMMARY], ids=["nothing", "no summary", "count off", "no count line"])
def test_a_suite_whose_reds_cannot_all_be_read_names_none(text):
    r = said(text)
    assert not r
    assert r.failing is None


def test_a_red_in_a_non_ascii_path_is_read_as_it_is_named():
    name = "tests/test_caf" + chr(0xe9) + ".py::test_one"
    r = said(SUMMARY.replace("tests/test_a.py::test_one", name)
             + "1 failed, 1 error in 0.10s" + NL)
    assert r.failing == [name, "tests/test_b.py::test_two[x]"]


def test_a_pass_names_no_red():
    assert said("1 passed in 0.01s" + NL, code=0).failing is None
