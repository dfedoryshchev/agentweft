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


def unproven(result):
    return getattr(result, "unproven", None)


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


TWO_AND_UNSURE = NL.join(["PASS a", "PASS b", "UNSURE: c"])


def test_an_unsure_check_is_unproven_and_the_rest_passing_passes():
    r = verdict(passes=3).run(TWO_AND_UNSURE)
    assert r, r.detail
    assert "1 unproven" in r.detail
    assert unproven(r) == ["UNSURE: c"]


def test_the_same_answer_with_a_fail_fails():
    r = verdict(passes=3).run(NL.join(["PASS a", "PASS b", "FAIL c"]))
    assert not r
    assert "FAIL c" in r.detail
    assert unproven(r) == []


@pytest.mark.parametrize("line", [
    "UNSURE: c",
    "- unsure whether the test came first",
    "NOT SURE the patch is the smallest",
    "UNVERIFIED: could not run the suite",
    "- UNVERIFIED: could not run the suite",
    "CANNOT CHECK the order, i only have the patch",
    "1. cannot check: no test was shown",
    "UNKNOWN whether the test came first",
])
def test_every_unsure_word_is_unproven_not_failed(line):
    r = verdict(passes=3).run(NL.join(["PASS a", "PASS b", line]))
    assert r, r.detail
    assert unproven(r) == [line.strip()]


def test_two_unsure_checks_are_both_on_record():
    r = verdict(passes=3).run(NL.join(["PASS a", "UNSURE b", "UNKNOWN c"]))
    assert r, r.detail
    assert "2 unproven" in r.detail
    assert unproven(r) == ["UNSURE b", "UNKNOWN c"]


def test_a_pass_answer_has_nothing_unproven():
    r = verdict(passes=3).run(THREE)
    assert unproven(r) == []
    assert "unproven" not in r.detail


@pytest.mark.parametrize("answer", [
    "UNVERIFIED: could not run the suite",
    "UNSURE: c",
    NL.join(["UNSURE a", "UNKNOWN b"]),
])
def test_an_answer_with_nothing_but_unsure_lines_fails(answer):
    r = verdict().run(answer)
    assert not r
    assert "no PASS" in r.detail
    assert unproven(r) == [l.strip() for l in answer.split(NL)]


def test_unsure_lines_do_not_make_up_for_a_dropped_check():
    r = verdict(passes=3).run(NL.join(["PASS a", "UNSURE c"]))
    assert not r
    assert "wanted 3" in r.detail


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
    assert unproven(r) == []


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


def handed(*answers):
    from agentweft.runner import summary

    passes = [summary.a_pass("verify.md", "verify", 1, None,
                             summary._gates([verdict(passes=3).run(a)], []),
                             False, "ok", a) for a in answers]
    return summary.build("demo-1", "demo", None, passes, {"git": False},
                         [], "")


def test_the_run_ends_done_with_the_unproven_count():
    lines = handed(TWO_AND_UNSURE)
    assert lines[0] == "# demo demo-1: done, 1 check unproven"
    assert "- done, 1 check unproven" in lines


def test_the_unproven_line_itself_is_in_the_handoff():
    lines = handed(TWO_AND_UNSURE)
    unverified = lines[lines.index("## not verified"):]
    assert "- verify.md unproven: UNSURE: c" in unverified


def test_two_unproven_checks_are_counted_in_the_plural():
    lines = handed(TWO_AND_UNSURE, NL.join(["PASS a", "PASS b", "UNKNOWN d"]))
    assert lines[0] == "# demo demo-1: done, 2 checks unproven"


def test_a_run_with_nothing_unproven_ends_the_way_it_did():
    lines = handed(THREE)
    assert lines[0] == "# demo demo-1: finished"
    assert not [l for l in lines if "unproven" in l]


def test_the_unproven_lines_survive_the_record_a_resume_reads():
    from agentweft.runner import summary

    kept = summary._gates([{"gate": "verdict", "ok": True, "detail": "x",
                            "unproven": ["UNSURE: c"]}], [])
    assert kept[0].get("unproven") == ["UNSURE: c"]


@pytest.mark.parametrize("passes", ["three", 0, -1, None])
def test_a_passes_that_is_not_a_positive_count_fails(passes):
    r = verdict(passes=passes).run(THREE)
    assert not r
    assert "passes" in r.detail
