import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import gates

NL = chr(10)
THREE = NL.join(["PASS the test is written before the patch",
                 "PASS the test fails on the unpatched code",
                 "PASS the patch is the smallest thing that turns it green"])


def verdict(**opts):
    return gates.build(dict({"gate": "verdict"}, **opts))


def test_pass_lines_pass():
    r = verdict(passes=3).run(THREE)
    assert r, r.detail


@pytest.mark.parametrize("line", [
    "FAIL the patch came first",
    "FAIL: the patch came first",
    "- FAIL: the patch came first",
    "* FAIL the patch came first",
    "+ FAIL the patch came first",
    "1. FAIL the patch came first",
    "2) FAIL the patch came first",
    "**FAIL** the patch came first",
    "- **FAIL**: the patch came first",
    "`FAIL` the patch came first",
    "> FAIL the patch came first",
    "### FAIL the patch came first",
    "  - FAIL - the patch came first",
    "fail: the patch came first",
    "Fail the patch came first",
    "FAIL",
])
def test_a_fail_line_in_any_list_shape_fails(line):
    r = verdict().run(THREE + NL + line)
    assert not r
    assert "FAIL" in r.detail.upper()
    assert line.strip() in r.detail


def test_a_fail_among_passes_fails_whichever_order():
    lines = THREE.split(NL)
    lines.insert(1, "- FAIL: the test passes on the unpatched code")
    assert not verdict(passes=3).run(NL.join(lines))


@pytest.mark.parametrize("answer", [
    "UNVERIFIED: could not run the suite",
    "- UNVERIFIED: could not run the suite",
    "CANNOT CHECK the order, i only have the patch",
    "1. cannot check: no test was shown",
    "UNKNOWN whether the test came first",
])
def test_an_answer_that_is_not_a_verdict_fails(answer):
    r = verdict().run(answer)
    assert not r
    assert "not a verdict" in r.detail


def test_an_unsure_line_among_passes_still_fails():
    r = verdict(passes=3).run(THREE + NL + "UNVERIFIED the suite was not run")
    assert not r
    assert "not a verdict" in r.detail


def test_an_answer_with_no_verdict_word_at_all_fails():
    r = verdict().run("looks good to me, the order was kept")
    assert not r
    assert "no PASS" in r.detail


def test_fewer_passes_than_asked_for_fails():
    r = verdict(passes=3).run(THREE.split(NL)[0])
    assert not r
    assert "1 PASS" in r.detail
    assert "3" in r.detail


@pytest.mark.parametrize("answer", ["", "   ", NL + "\t" + NL])
def test_an_empty_answer_is_an_answer_of_nothing(answer):
    r = verdict().run(answer)
    assert not r
    assert r.detail == "the step answered nothing"


@pytest.mark.parametrize("line", [
    "the test fails on the unpatched code, as it should",
    "PASS the test fails on the unpatched code",
    "failed attempts: none",
    "FAILS: KeyError",
    "PASSED is not a verdict word here",
    "a FAIL line would have stopped the run",
])
def test_a_fail_that_is_not_the_lead_word_is_not_a_fail_line(line):
    r = verdict().run("PASS the order was kept" + NL + line)
    assert r, r.detail


@pytest.mark.parametrize("passes", ["three", 0, -1, None])
def test_a_passes_that_is_not_a_positive_count_fails(passes):
    r = verdict(passes=passes).run(THREE)
    assert not r
    assert "passes" in r.detail
