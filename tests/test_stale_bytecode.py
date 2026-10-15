import os
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates

NL = chr(10)
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
        + "    assert add(1, 2) == 3" + NL)
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def edited_within_the_second(tmp_path, edit="code"):
    """the tests ran once and left bytecode (python's for the code, pytest's
    rewritten one for the test), then the code's fix or the test's
    correction went in at the same size with the same mtime, as a model's
    edit can within one second."""
    place = tmp_path / "repo"
    (place / "tests").mkdir(parents=True)
    calc = place / "calc.py"
    test = place / "tests" / "test_calc.py"
    calc.write_text(BUGGY if edit == "code" else FIXED, encoding="utf-8")
    test.write_text(TEST if edit == "code" else TEST.replace("== 3", "== 4"),
                    encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(place))
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
    first = subprocess.run(PYTEST + ["tests/test_calc.py"], cwd=str(place),
                           env=env, capture_output=True, text=True)
    assert first.returncode == 1, first.stdout
    edited, text = (calc, FIXED) if edit == "code" else (test, TEST)
    assert list((edited.parent / "__pycache__").glob(
        edited.stem + ".*.pyc"))
    was = edited.stat()
    edited.write_text(text, encoding="utf-8")
    os.utime(edited, ns=(was.st_atime_ns, was.st_mtime_ns))
    assert edited.stat().st_size == was.st_size
    return place


def test_a_corrected_test_is_run_as_it_is_now(tmp_path, monkeypatch):
    place = edited_within_the_second(tmp_path, edit="test")
    monkeypatch.setenv("PYTHONPATH", str(place))
    g = gates.build({"gate": "red-test", "red": False,
                     "command": PYTEST + ["{test}"]}, where=str(place))
    r = g.run("TEST: tests/test_calc.py" + NL + "patched it" + NL)
    assert r, r.detail


def test_the_red_test_gate_runs_the_code_as_it_is_now(tmp_path, monkeypatch):
    place = edited_within_the_second(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(place))
    g = gates.build({"gate": "red-test", "red": False,
                     "command": PYTEST + ["{test}"]}, where=str(place))
    r = g.run("TEST: tests/test_calc.py" + NL + "patched it" + NL)
    assert r, r.detail


def test_the_command_gate_runs_the_code_as_it_is_now(tmp_path, monkeypatch):
    place = edited_within_the_second(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(place))
    g = gates.build({"gate": "command", "command": PYTEST},
                    where=str(place))
    r = g.run("patched it")
    assert r, r.detail


def test_the_red_first_green_run_runs_the_code_as_it_is_now(tmp_path):
    place = edited_within_the_second(tmp_path)
    g = gates.build({"gate": "red-first", "command": PYTEST + ["{test}"]},
                    where=str(place))
    assert g.one(g.opts["command"], "tests/test_calc.py::test_add", place,
                 "") == ("green", "")


def test_a_gate_leaves_no_bytecode_in_the_place(tmp_path, monkeypatch):
    place = edited_within_the_second(tmp_path)
    for p in place.rglob("*.pyc"):
        p.unlink()
    monkeypatch.setenv("PYTHONPATH", str(place))
    g = gates.build({"gate": "command", "command": PYTEST},
                    where=str(place))
    assert g.run("patched it")
    assert list(place.rglob("*.pyc")) == []
