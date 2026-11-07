"""one ruling on a WRONG TEST claim covers every start test the same quoted
spec line makes wrong, and it stands at test-edits.

a want run adds a migration; two start tests each pin the last one against
the unchanged line "migrate runs every pending file in order". the worker
claims both in one answer: the run parks once, naming both, and the one
`override:` to that question lets both change at the test-edits check. a
claim made later in the run on another start test quoting the same line is
covered too, when that test's code as the run found it reads a word of the
line (a name or a string it uses, never a comment, a docstring or an assert
message), is red against the product now, and as the step left it is red
against the product as the run found it: the step's change is what made it
wrong. a line the run moved down by adding one above it is read where the
run found it.
a test that is still green as found, one the step broke besides that reads
nothing of the line, a claim on another line and a `request:` answer cover
nothing.

the shipped build-feature flow, on fake answers and a real git place.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops
from test_spec_conflict import a_place, folders, go, plain

NL = chr(10)
LINE = "migrate runs every pending file in order."
SPEC = ("# db" + NL + NL + "- " + LINE + NL
        + "- a name is kept as it was typed." + NL)
CODE = ("FILES = [\"0006\"]" + NL + NL + NL + "def pending(at):" + NL
        + "    return [f for f in FILES if int(f) > at]" + NL + NL + NL
        + "def name_of(text):" + NL + "    return text" + NL)
MORE = CODE.replace("[\"0006\"]", "[\"0006\", \"0007\"]")
DB_TEST = "tests/test_db.py::test_a_db_at_5_gets_only_0006"
MORE_TEST = "tests/test_db_more.py::test_from_5_the_list_is_0006"
NAMES_TEST = "tests/test_names.py::test_a_name_is_kept"


def a_test(name, body):
    return ("from db import name_of, pending" + NL + NL + NL + "def " + name
            + "():" + NL + "    assert " + body + NL)


DB_START = a_test("test_a_db_at_5_gets_only_0006", "pending(5) == [\"0006\"]")
DB_NOW = a_test("test_a_db_at_5_gets_only_0006",
                "pending(5) == [\"0006\", \"0007\"]")
MORE_START = a_test("test_from_5_the_list_is_0006",
                    "\", \".join(pending(5)) == \"0006\"")
MORE_NOW = a_test("test_from_5_the_list_is_0006",
                  "\", \".join(pending(5)) == \"0006, 0007\"")
NAMES_START = a_test("test_a_name_is_kept", "name_of(\"Rice\") == \"Rice\"")
NAMES_LOOSE = a_test("test_a_name_is_kept", "name_of(\"Rice\")")
NEW_TEST = a_test("test_a_db_at_6_gets_0007", "pending(6) == [\"0007\"]")
REQUEST = "add migration 0007, for items that were deleted"
PLAN = ("- behaviour: pending(6) is ['0007']" + NL + "  file: db.py" + NL)
TESTER = ("FAILS: assert [] == ['0007']" + NL + "TEST: tests/test_new.py"
          + NL)
BUILT = "- db.py: 0007 is a pending file" + NL
OK = "VERDICT: ok" + NL + NL + "- the change" + NL
OVERRIDE = ("override: the spec line quoted in the question holds; the tests"
            " the question names change to match it, each named in the"
            " handoff under this ruling, and nothing else changes with them.")
QUOTED = "TASK.md:3 \"" + LINE + "\""


def claim(test, spec=QUOTED):
    return ("WRONG TEST: " + test + NL + "why: it pins 0006 as the last file"
            + NL + "spec: " + spec + NL)


def place_of(tmp_path):
    a_place(tmp_path / "project", {
        "TASK.md": SPEC, "db.py": CODE, "conftest.py": "",
        "tests/test_db.py": DB_START, "tests/test_db_more.py": MORE_START,
        "tests/test_names.py": NAMES_START})
    return tmp_path / "project"


def first_leg(tmp_path, monkeypatch, said):
    place = place_of(tmp_path)

    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_new.py").write_text(NEW_TEST,
                                                         encoding="utf-8")
        if step == "worker.md":
            (place / "db.py").write_text(MORE, encoding="utf-8")
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN], "tester.md": [TESTER],
                               "worker.md": [said + BUILT]}),
                        edits, "--task", REQUEST)
    assert code == stops.EXIT_STOP, asked
    return place, folders(tmp_path)[-1]


def second_leg(tmp_path, monkeypatch, place, leg, said, writes,
               answer=OVERRIDE):
    def edits(step, n):
        if step == "worker.md":
            for rel, text in writes.items():
                (place / rel).write_text(text, encoding="utf-8")
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"worker.md": [said + BUILT],
                               "reviewer.md": [OK],
                               "reviewer-runs.md": [OK]}),
                        edits, "--resume", leg.name, "--answer", answer)
    return asked, code, folders(tmp_path)[-1]


def read(folder, name):
    path = folder / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


BOTH = {"tests/test_db.py": DB_NOW, "tests/test_db_more.py": MORE_NOW}


def test_two_claims_in_one_answer_ask_once_naming_both(tmp_path,
                                                       monkeypatch):
    _, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST) + NL
                       + claim(MORE_TEST))
    question = read(leg, "question.md")
    assert DB_TEST in question and MORE_TEST in question, question
    assert question.count(QUOTED) == 1


def test_one_override_covers_both_claimed_tests_at_test_edits(tmp_path,
                                                              monkeypatch):
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST) + NL
                           + claim(MORE_TEST))
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg, "",
                                     BOTH)
    gates = read(folder, "gates.md")
    assert "FAIL test-edits" not in gates, gates
    assert code == stops.EXIT_OK, read(folder, "why.md")
    assert asked.count("worker.md") == 1
    [ruled] = decisions.read(place)
    stamp = ruled.at.strftime(stops.STAMP) + " " + ruled.decided
    handoff = read(folder, "handoff.md")
    for test in (DB_TEST, MORE_TEST):
        assert test + " <- ruling " + stamp in handoff, test


def test_a_later_claim_on_the_same_line_is_covered(tmp_path, monkeypatch):
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST))
    assert MORE_TEST not in read(leg, "question.md")
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     claim(MORE_TEST), BOTH)
    assert code == stops.EXIT_OK, read(folder, "why.md")
    assert "FAIL test-edits" not in read(folder, "gates.md")
    assert asked.count("worker.md") == 1
    assert MORE_TEST + " <- ruling " in read(folder, "handoff.md")


ADDED = SPEC.replace("- " + LINE, "- 0007 holds the items that were deleted."
                     + NL + "- " + LINE)
MOVED = "TASK.md:4 \"" + LINE + "\""


def test_a_later_claim_on_a_line_the_run_moved_down_is_covered(
        tmp_path, monkeypatch):
    # the run adds a line above the quoted one, so both claims cite it one
    # line lower than the run found it
    place = place_of(tmp_path)

    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_new.py").write_text(NEW_TEST,
                                                         encoding="utf-8")
        if step == "worker.md":
            (place / "db.py").write_text(MORE, encoding="utf-8")
            (place / "TASK.md").write_text(ADDED, encoding="utf-8")
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [PLAN], "tester.md": [TESTER],
                               "worker.md": [claim(DB_TEST, MOVED) + BUILT]}),
                        edits, "--task", REQUEST)
    assert code == stops.EXIT_STOP, asked
    leg = folders(tmp_path)[-1]
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     claim(MORE_TEST, MOVED), BOTH)
    assert code == stops.EXIT_OK, read(folder, "gates.md")
    assert MORE_TEST + " <- ruling " in read(folder, "handoff.md")


def test_a_test_still_green_as_found_is_not_covered_by_the_line(
        tmp_path, monkeypatch):
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST) + NL
                           + claim(MORE_TEST))
    writes = dict(BOTH, **{"tests/test_names.py": NAMES_LOOSE})
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     claim(NAMES_TEST), writes)
    assert code != stops.EXIT_OK
    question = read(folder, "question.md")
    assert NAMES_TEST in question, question
    assert DB_TEST not in question and MORE_TEST not in question


LOWER = MORE.replace("    return text", "    return text.lower()")
NAMES_LOWER = a_test("test_a_name_is_kept", "name_of(\"Rice\") == \"rice\"")


def test_a_later_claim_on_a_test_that_shares_no_word_with_the_line_asks(
        tmp_path, monkeypatch):
    # the names test pins the name line; the move broke it, so it is red as
    # found, but nothing in it reads the migrate line it is claimed on
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST) + NL
                           + claim(MORE_TEST))
    writes = dict(BOTH, **{"tests/test_names.py": NAMES_LOWER,
                           "db.py": LOWER})
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     claim(NAMES_TEST), writes)
    assert code != stops.EXIT_OK
    assert NAMES_TEST + " <- ruling " not in read(folder, "handoff.md")
    assert NAMES_TEST in read(folder, "question.md")


@pytest.mark.parametrize("body", [
    'name_of("Rice") == "Rice", "every name keeps its case"',
    '(name_of("Rice")  # case kept, in order' + NL + '        == "Rice")'])
def test_a_line_s_word_only_in_a_message_or_comment_does_not_tie(
        tmp_path, monkeypatch, body):
    monkeypatch.setattr(sys.modules[__name__], "NAMES_START",
                        a_test("test_a_name_is_kept", body))
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST) + NL
                           + claim(MORE_TEST))
    writes = dict(BOTH, **{"tests/test_names.py": NAMES_LOWER,
                           "db.py": LOWER})
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     claim(NAMES_TEST), writes)
    assert code != stops.EXIT_OK
    assert NAMES_TEST + " <- ruling " not in read(folder, "handoff.md")


def test_a_test_reads_the_names_and_strings_its_code_uses(tmp_path):
    source = NL.join([
        "def test_qty(items):",
        '    """every qty is kept in order"""',
        "    # the file runs every pending migration",
        '    assert item()["qty"] == items.unit, "every name in order"', ""])
    assert ruling.code_words(source) == {"items", "item", "qty", "unit"}
    assert ruling.code_words("def broken(:") == set()
    place = place_of(tmp_path)
    (place / "tests" / "test_qty.py").write_text(
        "def test_qty():" + NL + '    assert item()["pending"] == 1  # order'
        + NL, encoding="utf-8")
    from agentweft.guardrails import snapshot
    from agentweft.runner.run import Run
    run = Run.__new__(Run)
    run.workdir, run.start = place, snapshot.take(place)
    line = ruling.words(LINE)
    assert run.found_words("tests/test_qty.py::test_qty") & line
    assert not run.found_words(NAMES_TEST) & line
    assert run.found_words(MORE_TEST) & line == {"pending"}


def test_a_claim_on_another_line_still_asks(tmp_path, monkeypatch):
    place, leg = first_leg(tmp_path, monkeypatch, claim(DB_TEST))
    other = claim(MORE_TEST, "TASK.md:4 \"a name is kept as it was typed.\"")
    asked, code, folder = second_leg(tmp_path, monkeypatch, place, leg,
                                     other, BOTH)
    assert code != stops.EXIT_OK
    assert MORE_TEST in read(folder, "question.md")


class Entry(object):
    def __init__(self, why, decided="ruling for worker.md: x"):
        self.why = why
        self.decided = decided


def entry(answer, leg="run-1"):
    return Entry("asked by worker.md in " + leg + ":" + NL + NL + "NEEDS: q"
                 + ruling.ANSWERED + answer + ruling.ANSWERED_BY + "me"
                 + ruling.ANSWERED_END)


def test_only_an_override_to_the_runners_own_question_answers_it():
    held = "TASK.md: - " + LINE
    asked = {"run-1": ruling.asked_wrong({"runner": ruling.wrong_asked(
        [DB_TEST], [held])})}
    assert ruling.answers_wrong(entry("override: they change"), asked) \
        == ((DB_TEST,), (held,))
    assert ruling.answers_wrong(entry("request: keep them"), asked) is None
    assert ruling.answers_wrong(entry("they change"), asked) is None
    assert ruling.answers_wrong(entry("override: x", "run-2"), asked) is None
    assert ruling.asked_wrong({"runner": {"id": "test-edits",
                                          "tests": [DB_TEST]}}) == ((), ())
    assert ruling.asked_wrong(None) == ((), ())


def test_the_lines_a_claim_quotes_are_read_as_the_run_found_them(tmp_path):
    (tmp_path / "TASK.md").write_text(SPEC, encoding="utf-8")
    assert ruling.claim_lines(QUOTED, tmp_path) == ["TASK.md: - " + LINE]
    assert ruling.claim_lines("TASK.md:9 \"not there\"", tmp_path) == []
    assert ruling.claim_lines("", tmp_path) == []
