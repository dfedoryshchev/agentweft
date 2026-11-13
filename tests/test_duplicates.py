"""new tests of a run that look alike are found at no model cost, handed to
the retro as a lead, and at most one nice-to-do a run names them."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard
from agentweft.orchestrate import facts
from agentweft.runner import retro

import test_supplied_red_test as supplied

NL = chr(10)
CALC = NL.join([
    "from calc import add, sub", "", "",
    "def test_add_old():", "    assert add(7, 8) == 15", "", "",
    "def test_add_one():", '    """one and two."""',
    "    assert add(1, 2) == 3", "", "",
    "def test_add_two():", "    # caf" + chr(0xE9),
    "    assert add(5, 6) == 11", "", "",
    "def test_sub():", "    assert sub(3, 1) == 2", "", "",
    "class TestCalc:", "    def test_add_three(self):",
    "        assert add(10, 20) == 30", ""])
OTHER = NL.join(["from calc import add", "", "",
                 "def test_add_four():", "    assert add(2, 2) == 4", ""])
NEW = ["tests/test_calc.py::test_add_one", "tests/test_calc.py::test_add_two",
       "tests/test_calc.py::test_sub",
       "tests/test_calc.py::TestCalc::test_add_three",
       "tests/test_other.py::test_add_four"]
GROUP = ["test_add_one", "test_add_two", "TestCalc::test_add_three"]


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=NL)


def a_place(root):
    put(root, "tests/test_calc.py", CALC)
    put(root, "tests/test_other.py", OTHER)
    put(root, "calc.py", "def add(a, b):" + NL + "    return a + b" + NL)
    return root


def test_new_tests_alike_in_one_file_are_one_group(tmp_path):
    from agentweft.runner import duplicates

    root = a_place(tmp_path / ("caf" + chr(0xE9)))
    assert duplicates.groups(root, NEW) == [
        ("unit", "tests/test_calc.py", GROUP)]
    assert duplicates.lines(duplicates.groups(root, NEW)) == [
        "- tests/test_calc.py (unit): test_add_one, test_add_two,"
        " TestCalc::test_add_three"]


@pytest.mark.parametrize("ids", [
    [], ["tests/test_calc.py"], ["tests/test_calc.py::test_add_one"],
    ["tests/test_gone.py::test_a", "tests/test_gone.py::test_b"],
    ["tests/test_calc.py::test_add_one", "tests/test_calc.py::test_sub"],
    ["tests/test_broken.py::test_a", "tests/test_broken.py::test_b"]],
    ids=["none", "a file", "one test", "a file not there", "not alike",
         "a file that does not parse"])
def test_no_two_alike_new_tests_is_no_group(tmp_path, ids):
    from agentweft.runner import duplicates

    root = a_place(tmp_path)
    put(root, "tests/test_broken.py", "def test_a(:" + NL)
    assert duplicates.groups(root, ids) == []
    assert duplicates.lines([]) == []


def test_the_lines_are_capped_and_the_rest_counted():
    from agentweft.runner import duplicates

    found = [("unit", "tests/test_" + str(n) + ".py", ["test_a", "test_b"])
             for n in range(duplicates.MOST + 2)]
    said = duplicates.lines(found)
    assert len(said) == duplicates.MOST + 1
    assert said[-1] == "- and 2 more groups"


def merge(claim, rel="tests/test_calc.py"):
    return ("fact", "", {"scope": [rel], "kind": "nice-to-do", "claim": claim,
                         "why": "the run wrote them one by one",
                         "source": 'seq 2 patcher.md; evidence: '
                                   'tests/test_calc.py:8 "def test_add_one():"'})


def test_one_nice_to_do_a_run_names_the_alike_tests(tmp_path):
    root = a_place(tmp_path)
    store, record = factsguard.Store(root), factsguard.Record(root)
    store.alike = [("unit", "tests/test_calc.py", GROUP)]
    done = retro.Maintained()
    retro.execute(store, record, [
        merge("merge test_add_one and test_add_two into one parametrized"
              " test"),
        merge("merge test_add_two and TestCalc::test_add_three into one"
              " parametrized test"),
        merge("give test_sub a case for a negative result")], done, "run-1")
    written = facts.read(root)
    assert [f.claim for f in written] == [
        "merge test_add_one and test_add_two into one parametrized test",
        "give test_sub a case for a negative result"]
    [(_, why)] = done.refused
    assert why == ("one nice-to-do a run names the new tests that look alike,"
                   " and " + written[0].id + " does")


def test_the_retro_is_handed_the_new_tests_that_look_alike(tmp_path,
                                                           monkeypatch):
    sent = {}
    alike = ("from calc import add" + NL + NL + NL + "def test_zero():" + NL
             + "    assert add(0, 0) == 0" + NL + NL + NL
             + "def test_zeros():" + NL + "    assert add(0, 0.0) == 0" + NL)
    supplied.run_it(tmp_path, monkeypatch, {"tests/test_more.py": alike},
                    sent=sent)
    said = sent[supplied.RETRO]
    assert "new tests this run wrote that look alike, a lead" in said
    assert NL + "- tests/test_more.py (unit): test_zero, test_zeros" + NL \
        in said
    assert "look alike" not in sent["patcher.md"]


def test_a_run_with_no_alike_new_tests_hands_the_retro_no_such_part(
        tmp_path, monkeypatch):
    sent = {}
    supplied.run_it(tmp_path, monkeypatch, {"tests/test_more.py":
                                            supplied.PIN}, sent=sent)
    assert "look alike" not in sent[supplied.RETRO]
