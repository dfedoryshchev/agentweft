"""a recording made on one machine replays on another: what a gate said about
the place it ran in, and the python that ran it, is hashed the same whatever
the OS, the temp folder or the interpreter, and nothing else is let go."""
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
import yaml

sys.path.insert(0, ".")
from agentweft.evals import harness, recording
from agentweft.providers import fake_provider

SAID = ("\n\nyour last answer failed a gate, so this step runs again. the"
        " gate said:\n\n")
WIN = PureWindowsPath(r"C:\Temp\tmpa1b2c3\place")
NIX = PurePosixPath("/tmp/tmpz9y8x7/place")


def gate_said(place, sep, secs):
    return ("# patcher\n\nfix it.\n" + SAID + "command: exit 1: "
            + "tests" + sep + "test_add.py:5: in test_add\n"
            "    assert add(1, 2) == 3\nE   assert -1 == 3\n"
            "1 failed in " + secs + "s\nred-test: test_calc.py is not in "
            + str(place) + ", so the test was never written\n")


def test_the_marker_is_what_the_runner_writes():
    from agentweft.runner import engine

    assert engine.gate_told([]).startswith("\n\n" + recording.GATE_SAID)


def test_the_gate_words_hash_the_same_on_windows_and_on_linux():
    on_windows = gate_said(WIN, "\\", "0.03")
    on_linux = gate_said(NIX, "/", "0.21")
    assert on_windows != on_linux
    assert (recording.digest(on_windows, WIN)
            == recording.digest(on_linux, NIX))


def test_the_place_is_found_in_either_spelling_and_in_crlf():
    posix = str(WIN).replace("\\", "/")
    text = "ran in " + posix + "/calc.py\r\nand in " + str(WIN) + "\r\n"
    assert recording.digest(text, WIN) == recording.digest(
        "ran in " + str(NIX) + "/calc.py\nand in " + str(NIX) + "\n", NIX)


def test_the_interpreter_path_is_not_part_of_the_hash(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\Python\python.exe")
    windows = recording.digest(SAID + r"not on PATH: C:\Python\python.exe")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert recording.digest(SAID + "not on PATH: /usr/bin/python3") == windows


def test_nothing_else_is_let_go():
    words = gate_said(NIX, "/", "0.21")
    assert recording.digest(words, NIX) != recording.digest(
        words.replace("assert -1 == 3", "assert -1 == 4"), NIX)
    # a backslash in the words the step was given, not in what a gate said
    assert recording.digest("match a\\d here", NIX) != recording.digest(
        "match a/d here", NIX)
    # a prompt with nothing to make neutral hashes as it always did, so the
    # recordings already kept still replay
    plain = "# worker\n\nfind the bug.\n"
    assert recording.digest(plain, NIX) == hashlib.sha256(
        plain.encode("utf-8")).hexdigest()


BUGGY = "def add(a, b):\n    return a - b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
RED = "FAILS: assert -1 == 3\nTEST: tests/test_add.py\n"


@pytest.fixture
def unwritten(tmp_path, monkeypatch):
    """a case whose worker first names a test it never wrote, so the red-test
    gate sends it back saying the place it looked in."""
    root = tmp_path / "evals"
    case = root / "fix-with-test" / "cases" / "unwritten"
    (case / "place").mkdir(parents=True)
    (case / "place" / "calc.py").write_text(BUGGY, encoding="utf-8")
    (case / "case.yaml").write_text(yaml.safe_dump(
        {"task": "add(1, 2) returns -1", "place": "place",
         "provider": {"provider": "fake", "replies": {
             "worker.md": [RED, {"say": RED,
                                 "writes": {"tests/test_add.py": TEST}}],
             "patcher.md": [{"say": "TEST: tests/test_add.py\n",
                             "writes": {"calc.py": BUGGY.replace("-", "+")}}]}},
         "expect": {"outcome": "done"}}), encoding="utf-8")
    monkeypatch.setattr(harness, "ROOT", root)
    monkeypatch.setattr(harness, "LAST", root / ".last.json")
    return case


def test_a_gate_that_named_the_place_replays_in_another_place(unwritten,
                                                               monkeypatch):
    live = harness.run_flow_for("fix-with-test", harness.load_case(unwritten),
                                record=True)
    assert live[2] == ""
    assert [l["outcome"] for l in live.steps] == ["gate failed", "ok", "ok"]
    kept = json.loads((unwritten / recording.FILE).read_text(encoding="utf-8"))
    assert len(kept["calls"]) == 3

    def ask(self, prompt, timeout=None):
        raise AssertionError("a replayed case called its provider")
    monkeypatch.setattr(fake_provider.FakeProvider, "ask", ask)
    again = harness.run_flow_for("fix-with-test", harness.load_case(unwritten))
    assert again[2] == ""
    assert [l["outcome"] for l in again.steps] == ["gate failed", "ok", "ok"]
