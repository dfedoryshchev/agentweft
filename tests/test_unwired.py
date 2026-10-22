"""new code a run added that nothing in the product calls is named in the
handoff, with the step that wrote it: a feature written and never wired in
reads the same to the suite as one that is.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import unwired

NL = chr(10)


def names(found):
    return [(f["path"], f["line"], f["name"], f["tests"]) for f in found]


def test_a_new_def_only_a_test_calls_is_named_and_one_another_file_calls_is_not():
    added = {"calc.py": [(4, "def mul(a, b):"), (5, "    return a * b"),
                         (8, "def scale(x):"), (11, "class Report:")]}
    product = {"calc.py": "def add(a, b):\n\n\ndef mul(a, b):\n    return a * b"
                          "\n\n\ndef scale(x):\n    return x\n\n\nclass Report:"
                          "\n    pass\n",
               "cli.py": "from calc import scale\nprint(scale(2))\n"}
    tests = {"tests/test_calc.py": "from calc import mul\n"}
    assert names(unwired.found(added, product, tests)) == [
        ("calc.py", 4, "mul", True), ("calc.py", 11, "Report", False)]


def test_a_helper_its_own_file_calls_is_wired_and_a_dunder_is_never_named():
    added = {"calc.py": [(1, "def _half(x):"), (4, "    def __repr__(self):")]}
    product = {"calc.py": "def _half(x):\n    return x / 2\n\n"
                          "    def __repr__(self):\n        return ''\n"
                          "def mean(xs):\n    return _half(sum(xs))\n"}
    assert unwired.found(added, product, {}) == []


def test_the_handoff_line_names_the_place_who_calls_it_and_the_writer():
    found = [{"path": "calc.py", "line": 4, "kind": "def", "name": "mul",
              "tests": True},
             {"path": "calc.py", "line": 11, "kind": "class", "name": "Report",
              "tests": False}]
    assert unwired.lines(found, {"calc.py": ["worker.md"]}) == [
        "- not called from the product: calc.py:4 def mul, only tests call"
        " it (worker.md)",
        "- not called from the product: calc.py:11 class Report, nothing"
        " calls it (worker.md)"]
    assert unwired.lines(found[:1], {}) == [
        "- not called from the product: calc.py:4 def mul, only tests call"
        " it"]


def test_a_run_names_the_unwired_code_its_worker_wrote_in_the_handoff(
        tmp_path, monkeypatch):
    import test_wrong_test as wt

    after = wt.AFTER + NL + NL + "def unused(x):" + NL + "    return x" + NL
    answers = {"planner.md": [wt.PLAN], "tester.md": [wt.TESTER],
               "worker.md": [wt.WORKER], "reviewer.md": [wt.OK],
               "reviewer-runs.md": [wt.OK]}
    writes = {"tester.md": [("tests/test_mul.py", wt.RIGHT)],
              "worker.md": [("calc.py", after)]}
    _, _, code, folder, _ = wt.run_it(tmp_path, monkeypatch, answers, writes)
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    assert code == 0
    assert ("- not called from the product: calc.py:5 def mul, only tests"
            " call it (worker.md)") in handoff
    assert ("- not called from the product: calc.py:9 def unused, nothing"
            " calls it (worker.md)") in handoff
    changed = handoff.split("## changed")[1].split("## read")[0]
    assert "def unused" in changed
