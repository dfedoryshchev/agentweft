import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates


def test_red_is_the_default_and_passes_on_a_fails_line():
    g = gates.build({"gate": "red-test"})
    r = g.run("wrote the test\nFAILS: KeyError: 'id'")
    assert r
    assert r.detail == "red"


def test_red_fails_when_the_output_has_no_marker():
    g = gates.build({"gate": "red-test", "red": True})
    r = g.run("wrote the test, it fails on the old code")
    assert not r
    assert "no FAILS: line" in r.detail


def test_green_fails_when_the_marker_is_still_there():
    g = gates.build({"gate": "red-test", "red": False})
    r = g.run("patched it\nFAILS: KeyError: 'id'")
    assert not r
    assert "still there after the patch" in r.detail


def test_green_passes_once_the_marker_is_gone():
    g = gates.build({"gate": "red-test", "red": False})
    r = g.run("patched it, 1 passed")
    assert r
    assert r.detail == "green"


def test_the_marker_can_be_changed():
    g = gates.build({"gate": "red-test", "marker": "RED:"})
    assert g.run("RED: AssertionError")
    assert not g.run("FAILS: AssertionError")


def test_it_is_a_substring_match_anywhere_in_the_text():
    g = gates.build({"gate": "red-test"})
    assert g.run("the old code said FAILS: before i looked")
    assert g.run("NOTFAILS: at all")
    assert not g.run("fails: lowercase")


def test_the_words_are_all_it_checks():
    g = gates.build({"gate": "red-test"})
    assert g.run("FAILS: this test was never written or run")
