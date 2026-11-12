"""the red-first line counts what the red proof holds, and the head is whole.

red first is the run's headline proof, so its line says how many tests were
written first and shown red, how many were added after the code went green,
which of those pass without the fix, and how many a review added and proved
red on the start commit, each count apart and read from the red proof, never
one number for all. the head's suite line, its decision, the lead's
decisions and every recommendation are printed whole, never cut with `...`.
a command a step ran for several checks is printed once and named after.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import handoff, stops, summary

NO_GIT = {"git": False}
NL = chr(10)
FIRST = ["tests/test_t.py::test_since_is_inclusive",
         "tests/test_t.py::test_until_is_strict"]
COVER = "tests/test_more.py::test_bound_accepts_edges"
PIN = "tests/test_more.py::test_default_is_comma"
REVIEW = "tests/test_t.py::test_negative_offset_minutes"


def a_pass(step, said, outcome="ok", gates=(), case=None):
    return summary.a_pass(step, step[:-3], 1.0, handoff.parse(said),
                          list(gates), False, outcome, said, case=case)


def did(line):
    return ("HANDOFF" + NL + "DID:" + NL + "- " + line + NL + "END HANDOFF"
            + NL)


def replayed():
    tests = [{"test": i, "before": "red", "kind": "assertion",
              "after": "green", "red_on": "assertion"} for i in FIRST]
    tests.append({"test": COVER, "before": "red", "kind": "ImportError",
                  "after": "green", "red_on": "missing name",
                  "added": "after green", "counts": "coverage"})
    tests.append({"test": PIN, "before": "green", "kind": "",
                  "after": "green", "added": "after green", "counts": "pin"})
    return {"gate": "red-first", "ok": True,
            "command": "python -m pytest -q {test}",
            "detail": "3 of 4 new tests red without the fix and green with"
            " it: " + ", ".join(FIRST + [COVER]) + "; green without it too: "
            + PIN + "; added after green: 1 coverage, 1 pin; " + PIN
            + " pins current behaviour, not counted as coverage",
            "tests": tests}


ON_REVIEW = {"gate": "red-test", "ok": True,
             "command": "python -m pytest -q " + REVIEW,
             "detail": "red, exit 1 (on the start commit, without the product"
             " code written since)"}
PROOF = {"how": "gate", "gate": "red-test", "step": "tester.md",
         "source": "written", "ids": list(FIRST),
         "tests": {"tests/test_t.py": "0"}}


def a_feature(proof=PROOF):
    passes = [a_pass("tester.md", did("wrote 2 failing tests"),
                     gates=[{"gate": "red-test", "ok": True,
                             "command": "python -m pytest -q tests/test_t.py",
                             "detail": "red, exit 1"}]),
              a_pass("worker.md", did("built the window"),
                     gates=[replayed()]),
              a_pass("reviewer.md", did("asked for a case"), "routed"),
              a_pass("tester.md", did("added the case"), gates=[ON_REVIEW],
                     case={"seq": 3, "step": "reviewer.md", "red": False})]
    return summary.build("f-1", "f", "add the window", passes, NO_GIT, [],
                         "1 call", proof=proof)


def suite(lines):
    return next(l for l in lines if l.startswith("suite: "))


def test_red_first_counts_written_first_after_green_and_on_review_apart():
    lines = a_feature()
    want = ("red first: shown on worker.md: 2 written first and red; 1 added"
            " after green (coverage); 1 added after green that passes without"
            " the fix (a pin); 1 added on review, red on the start commit")
    assert want in suite(lines), suite(lines)
    assert "- " + want in lines
    assert "::" not in suite(lines)


def test_a_supplied_red_is_said_as_the_proof_with_nothing_written_first():
    supplied = dict(PROOF, source="supplied", ids=[],
                    tests={"tests/test_bug_report.py": "0"})
    line = suite(a_feature(supplied))
    assert ("red first: shown on worker.md: 0 written first (the supplied"
            " test is the proof: tests/test_bug_report.py); 3 added after"
            " green (coverage); 1 added after green that passes without the"
            " fix (a pin)") in line, line


def test_the_ids_of_the_replay_are_listed_once_test_by_test():
    text = NL.join(a_feature())
    record = text.split("## tests and checks" + NL)[1].split(NL + "## ")[0]
    assert record.count(FIRST[0]) == 1, record
    assert ("- worker.md: PASS red-first - 2 written first and red; 1 added"
            " after green (coverage); 1 added after green that passes without"
            " the fix (a pin); each test is listed below (python -m pytest -q"
            " {test})") in record, record


LONG = ("leave it as is: the request asks for the value as given, and the"
        " existing option error repeats values the same way, so escaping only"
        " this one would make two error forms where the spec has one; if a"
        " person wants one line always, escape every option value at once in"
        " the one place that formats the error, and add a spec line saying"
        " so")


def test_the_one_decision_and_its_recommendation_are_never_cut():
    said = ("HANDOFF" + NL + "DID:" + NL + "- checked it" + NL + "QUESTION: "
            + "Should the error print C as given when C is CR or LF, which"
            " breaks the one-line stderr rule at TASK.md:3, given that the"
            " request names the format and the option error already does"
            " the same?" + NL + "RECOMMEND: " + LONG + NL + "SIZE: none if"
            " left" + NL + "END HANDOFF" + NL)
    long_did = "x" * 200
    passes = [a_pass("step" + str(n) + ".md", (
        "HANDOFF" + NL + "DID:" + NL + "- did " + long_did + NL
        + "DOUBTS:" + NL + "- doubt " + str(n) + " " + long_did + NL
        + "NOT VERIFIED:" + NL + "- unchecked " + str(n) + " " + long_did + NL
        + "END HANDOFF" + NL)) for n in range(12)]
    lines = summary.build("f-1", "f", "add it", passes + [
        a_pass("reviewer-runs.md", said)], NO_GIT, [], "1 call")
    top = NL.join(lines[:lines.index("## full record")])
    assert "recommendation: " + LONG + " (size: none if left)" in top, top
    assert "the same?" + NL in top


def test_a_conflict_stops_recommendation_is_whole_in_the_head():
    said = ("CONFLICT: the request contradicts TASK.md:158" + NL
            + "RECOMMEND: " + LONG + NL + "SIZE: a spec line" + NL)
    lines = summary.build("f-1", "f", "export as numbers",
                          [a_pass("worker.md", said, "conflict")], NO_GIT, [],
                          "1 call", stopped={
                              "cause": stops.CONFLICT, "at": "worker.md",
                              "why": "the request contradicts TASK.md:158",
                              "question": said})
    top = NL.join(lines[:lines.index("## full record")])
    assert LONG in top, top


def test_a_long_suite_line_is_never_cut():
    failed = {"gate": "red-first", "ok": False, "command": "python -m pytest"
              " -q {test}", "detail": "tests/test_t.py::test_since_is_"
              "inclusive does not pass with the fix: exit 1 " + "y" * 300}
    passes = [a_pass("step" + str(n) + ".md", (
        "HANDOFF" + NL + "DID:" + NL + "- did " + "x" * 200 + NL
        + "DOUBTS:" + NL + "- doubt " + str(n) + " " + "x" * 200 + NL
        + "END HANDOFF" + NL)) for n in range(12)]
    lines = summary.build("f-1", "f", "add it " + "z" * 4000, passes + [
        a_pass("worker.md", did("built it"), gates=[failed])], NO_GIT, [],
        "1 call")
    assert lines[2].endswith("..."), lines[2]
    line = suite(lines)
    assert line.endswith("y" * 300 + "."), line


COMMAND = ("cd work && for a in --since --until --strict; do printf 'x'"
           " | python -m logsift filter $a; echo rc=$?; done 2>&1")


def test_a_command_behind_several_checks_is_printed_once():
    said = ("HANDOFF" + NL + "DID:" + NL + "- ran the filters" + NL
            + "VERIFIED:" + NL
            + "- since is inclusive" + NL + "  cmd: " + COMMAND + NL
            + "  saw: rc=0" + NL
            + "- until is strict" + NL + "  cmd: " + COMMAND + NL
            + "  saw: rc=2" + NL
            + "- strict reports the line" + NL + "  cmd: " + COMMAND + NL
            + "  saw: error: -:3" + NL + "END HANDOFF" + NL)
    text = NL.join(summary.build("f-1", "f", "add it",
                                 [a_pass("reviewer.md", said)], NO_GIT, [],
                                 "1 call"))
    assert text.count(COMMAND) == 1, text
    assert "- reviewer verified: since is inclusive | cmd [c1]: " + COMMAND \
        in text
    assert "- reviewer verified: until is strict | cmd: c1, printed above |" \
        " saw: rc=2" in text
