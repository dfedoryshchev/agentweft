"""a run records the state of the suite it started from, cached by commit.

`baseline:` in flow.yaml: `on` runs the start tests on the start state as the
run starts, `auto` only once something comes back red, `off` never. the
outcome is kept as runs/<id>/baseline.json and under the runs root by the
start commit, so a second run on the same commit runs nothing. a test red at
the start is run again three times, and one that turns green is flaky. a test
red at the start is named in the handoff as red when the run started.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import starttests
from agentweft.runner import state, stops

from test_red_order import a_flow
from test_start_tests import (BREAKS, COUNT, KNOWN_RED, NL, SORTED, TESTER,
                              WORKER, a_place, folders, git, read, running)

KNOWN = "tests/test_known.py::test_known"
WOBBLY = "tests/test_wobbly.py::test_wobbly"
QUIET = ("  - role: worker" + NL + "    prompt: worker.md" + NL
         + "    writes: none" + NL)
NOTHING = {"worker.md": ({}, "- nothing to change" + NL)}


def a_flow_with(tmp_path, steps, said):
    a_flow(tmp_path, "build", steps)
    flow = tmp_path / "flows" / "build" / "flow.yaml"
    flow.write_text(read(flow) + "baseline: " + said + NL, encoding="utf-8")


def counting(monkeypatch):
    """-> the list each pytest run of the start tests is noted in, as
    (files, where)."""
    ran = []
    real = starttests.run_tests

    def counted(base, files, there, timeout):
        ran.append((list(files), str(there)))
        return real(base, files, there, timeout)

    monkeypatch.setattr(starttests, "run_tests", counted)
    return ran


def kept(folder):
    path = folder / "baseline.json"
    assert path.is_file(), "no baseline.json in " + folder.name
    return json.loads(read(path))


def test_on_records_the_suite_as_the_run_starts(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, QUIET, "on")
    code, called = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    assert called == ["worker.md"]
    found = kept(folders()[-1])
    assert found["commit"] == git(place, "rev-parse", "HEAD").strip()
    assert found["from"] == "run"
    assert "tests/test_report.py::test_alphabetical" in found["passed"]
    assert list(found["red"]) == [KNOWN]
    assert found["flaky"] == []


def test_a_second_run_on_the_same_commit_reads_the_cache(tmp_path,
                                                         monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, QUIET, "on")
    ran = counting(monkeypatch)
    code, _ = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    first = len(ran)
    assert first >= 1
    code, _ = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    assert len(ran) == first, "the second run ran the suite again"
    second = kept(folders()[-1])
    assert second["from"] == "cache"
    assert list(second["red"]) == [KNOWN]


def test_a_loose_edit_is_its_own_baseline(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, QUIET, "on")
    ran = counting(monkeypatch)
    running(tmp_path, monkeypatch, place, NOTHING, False)
    first = len(ran)
    (place / "tests" / "test_known.py").write_text(
        KNOWN_RED.replace("== []", "== ['a']"), encoding="utf-8")
    code, _ = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    assert len(ran) > first
    found = kept(folders()[-1])
    assert found["from"] == "run"
    assert found["dirty"]
    assert found["red"] == {}


def test_a_test_that_turns_green_on_a_retry_is_flaky(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    count = (tmp_path / "count").as_posix()
    (place / "tests" / "test_wobbly.py").write_text(
        "import pathlib" + NL + NL + NL + "def test_wobbly():" + NL
        + "    p = pathlib.Path('" + count + "')" + NL
        + "    n = int(p.read_text()) if p.exists() else 0" + NL
        + "    p.write_text(str(n + 1))" + NL
        + "    assert n > 0" + NL, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "wobbly")
    a_flow_with(tmp_path, QUIET, "on")
    code, _ = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    found = kept(folders()[-1])
    assert found["flaky"] == [WOBBLY]
    assert WOBBLY not in found["red"]
    assert list(found["red"]) == [KNOWN]
    handoff = read(folders()[-1] / "handoff.md")
    assert "flaky when the run started" in handoff
    assert WOBBLY in handoff


def test_an_inherited_red_is_named_in_the_handoff(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, QUIET, "on")
    code, _ = running(tmp_path, monkeypatch, place, NOTHING, False)
    assert code == 0
    handoff = read(folders()[-1] / "handoff.md")
    line = [l for l in handoff.split(NL) if KNOWN in l]
    assert line and "red when the run started" in line[0]


def test_auto_waits_for_a_red_then_the_replay_reads_the_baseline(
        tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    counted = SORTED + NL + NL + "def count(names):" + NL \
        + "    return len(names)" + NL
    code, _ = running(tmp_path, monkeypatch, place, {
        "tester.md": ({"tests/test_count.py": COUNT},
                      "FAILS: assert False" + NL + "TEST: tests/test_count.py"
                      + NL),
        "worker.md": ({"report.py": counted}, "- report.py: count" + NL)},
        False)
    assert code == 0
    # test_known is red now too, so the start state is read once, lazily
    found = kept(folders()[-1])
    assert list(found["red"]) == [KNOWN]
    handoff = read(folders()[-1] / "handoff.md")
    assert "red when the run started" in handoff


def test_on_hands_the_replay_its_baseline(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, TESTER + WORKER, "on")
    asked = []
    real = starttests.tests_in

    def watched(start, files, base, timeout, now):
        asked.append(now)
        return real(start, files, base, timeout, now)

    monkeypatch.setattr(starttests, "tests_in", watched)
    code, _ = running(tmp_path, monkeypatch, place, BREAKS, False)
    assert code == stops.exit_code(stops.CONFLICT)
    assert False not in asked, "the replay ran the start state itself"
    assert "tests/test_report.py::test_alphabetical" in read(
        folders()[-1] / "why.md")


def test_off_records_nothing(tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    a_flow_with(tmp_path, TESTER + WORKER, "off")
    code, _ = running(tmp_path, monkeypatch, place, BREAKS, False)
    assert code == stops.exit_code(stops.CONFLICT)
    assert not (folders()[-1] / "baseline.json").exists()
    assert not list(state.RUNS.glob("baseline-*.json"))


def test_the_setting_is_a_flow_key_with_three_values():
    from agentweft.flow import spec

    base = {"name": "x", "steps": [{"role": "a"}]}
    for said in ("auto", "on", "off", True, False):
        assert spec.check(dict(base, baseline=said)) == [], said
    bad = spec.check(dict(base, baseline="sometimes"))
    assert any("baseline" in b for b in bad)
