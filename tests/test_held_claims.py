"""a WRONG TEST claim the test-edits check took holds for the rest of the run.

on an override run a step changes a start test that pins a ruled line and
names it on a WRONG TEST line; the test-edits check passes it. a reviewer
then sends the step back for something else, and the step answers again
without repeating the claim. the claim still stands: the check reads it
from the run's own record, and the handoff lists the test under the ruling.
a start test the later go changes needs a claim of its own, a claim whose
quoted line no longer reads where it cited it covers nothing, and a new run
starts with no claims, while a resume carries them.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import manifest, stops

from test_named_spec_files import NAMED, OVERRIDE, TESTER, first_plan
from test_ruled_start_tests import (CURSOR_ENVELOPE, EDITED, ENVELOPE_TEST,
                                    FIRST_PAGE_TEST, FOUND, NAMES_SORTED,
                                    NAMES_TEST, TYPED_PLAN, built, edits_of,
                                    place_of, record, stamp_of, wrong)
from test_spec_conflict import folders, go, plain

NL = chr(10)
REDO = "VERDICT: redo" + NL + NL + "- cursor() is not tried past the end" + NL
OK = "VERDICT: ok" + NL + NL + "- the change" + NL
CLAIMED = built(wrong(ENVELOPE_TEST, FOUND[0]), wrong(FIRST_PAGE_TEST,
                                                      FOUND[1]))
CLAIMED_EDIT = built(wrong(ENVELOPE_TEST, EDITED[1]), wrong(FIRST_PAGE_TEST,
                                                            EDITED[0]))
AGAIN = built()


def redone(tmp_path, monkeypatch, first=CLAIMED, then=AGAIN, later=None):
    """an override run whose worker claims the start tests it changes on
    its first go, is sent back by the reviewer, and answers `then` on its
    second go, where `later(place)` writes more. -> (steps asked on the
    second leg, its exit code)."""
    place = place_of(tmp_path, monkeypatch)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [first_plan(NAMED)]}),
                        lambda s, n: None, "--task", NAMED)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    writes = edits_of(place, rewrite=CURSOR_ENVELOPE)

    def edits(step, n):
        writes(step, n)
        if step == "worker.md" and n >= 1 and later is not None:
            later(place)
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [TYPED_PLAN],
                               "tester.md": [TESTER],
                               "worker.md": [first, then],
                               "reviewer.md": [REDO, OK],
                               "reviewer-runs.md": [OK]}),
                        edits, "--resume", leg.name, "--answer", OVERRIDE)
    return asked, code


def test_a_claim_taken_on_one_go_holds_when_a_later_go_does_not_repeat_it(
        tmp_path, monkeypatch):
    asked, code = redone(tmp_path, monkeypatch)
    gates = record(tmp_path, "gates.md")
    assert asked.count("worker.md") == 2, asked
    assert "FAIL test-edits" not in gates, gates
    assert code == stops.EXIT_OK, gates
    handoff = record(tmp_path, "handoff.md")
    for test in (ENVELOPE_TEST, FIRST_PAGE_TEST):
        assert test + " <- ruling " + stamp_of(tmp_path) in handoff, test


def test_a_start_test_the_later_go_changes_needs_its_own_claim(
        tmp_path, monkeypatch):
    def sorts(place):
        (place / "tests" / "test_names.py").write_text(NAMES_SORTED,
                                                       encoding="utf-8")
    asked, code = redone(tmp_path, monkeypatch, later=sorts)
    assert code != stops.EXIT_OK
    gates = record(tmp_path, "gates.md")
    assert "FAIL test-edits" in gates
    assert NAMES_TEST in gates.split("FAIL test-edits")[-1]


def test_a_claim_whose_quoted_line_moved_on_covers_nothing(tmp_path,
                                                          monkeypatch):
    def rewords(place):
        api = (place / "docs" / "api.md").read_text(encoding="utf-8")
        (place / "docs" / "api.md").write_text(
            api.replace("`{items, next}`", "`{items, next, size}`"),
            encoding="utf-8")
    asked, code = redone(tmp_path, monkeypatch, first=CLAIMED_EDIT,
                         later=rewords)
    assert code != stops.EXIT_OK
    assert ENVELOPE_TEST in record(tmp_path, "gates.md").split(
        "FAIL test-edits")[-1]


def test_a_resume_carries_the_claims_and_a_new_run_starts_with_none(
        tmp_path):
    old = manifest.Manifest.new(tmp_path / "a", "build-1", "build", "build",
                                ["worker.md"], ("", {}))
    old.data["claims"] = ["WRONG TEST: tests/test_a.py::test_one"]
    carried = old.carried(tmp_path / "b", "build-2", ["worker.md"], ("", {}))
    assert carried.data["claims"] == old.data["claims"]
    fresh = manifest.Manifest.new(tmp_path / "c", "build-3", "build", "build",
                                  ["worker.md"], ("", {}))
    assert "claims" not in fresh.data
