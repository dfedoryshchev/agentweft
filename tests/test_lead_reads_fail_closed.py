"""a typed line of the lead's page that the program cannot read parks the
question, never decides it: a `spec` line in none of the five taught forms,
a QUESTION key the block's reader drops (bulleted, `-` for its colon), a
RECOMMEND that holds no choice to record, and a start test named in any
spelling, by the question, its cites, its SETTLED BY or its RECOMMEND."""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot
from agentweft.runner import asking
from test_lead_asks_by_risk import NL, a_place, asking_, page, routed

REC = "convert when reading, with no migration"
Q = ("should items with another unit become pcs through a new migration 0008"
     " that rewrites the stored rows, or when they are read?")


def parks(said, ruled):
    return bool(said) and ruled == []


@pytest.mark.parametrize("name", [
    "test_migrations.py:3",
    "./tests/test_migrations.py:3",
    "Tests/Test_Migrations.py:3",
    "tests//test_migrations.py:3",
    "tests/./test_migrations.py:3",
    "tests\\test_migrations.py:3",
    "TESTS/TEST_MIGRATIONS.PY:3",
    "the absolute path",
    "tests/test_migrations.py::test_the_last_migration_is_0007",
    "`tests/test_migrations.py`",
])
@pytest.mark.parametrize("git", [False, True])
def test_a_start_test_named_in_any_spelling_parks(tmp_path, name, git):
    place = a_place(tmp_path / "p", git=git)
    start = snapshot.take(place) if git else None
    if name == "the absolute path":
        name = str(place / "tests" / "test_migrations.py") + ":3"
    text = page(*asking_(Q + " " + name + " pins 0007 as the last migration",
                         "none", REC))
    said, ruled = routed(place, text, start=start)
    assert parks(said, ruled), (name, ruled)
    assert "a test the run started with" in said


def test_a_start_test_named_by_its_file_name_is_matched_to_its_path(
        tmp_path):
    place = a_place(tmp_path, git=True)
    start = snapshot.take(place)
    text = page(*asking_(Q + " test_migrations.py:3 pins 0007", "none", REC))
    said, _ = routed(place, text, start=start)
    assert "- tests/test_migrations.py::test_the_last_migration_is_0007 - a" \
        " test the run started with" in said.split(NL)


def test_with_no_snapshot_a_name_that_looks_like_a_test_parks(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_("Should tests/test_units.py check the unit?", "none",
                         "yes, check it"))
    said, ruled = routed(place, text)
    assert parks(said, ruled)


def test_a_recommendation_naming_a_start_test_parks(tmp_path):
    place = a_place(tmp_path, git=True)
    start = snapshot.take(place)
    text = page(*asking_(Q, "none", "add migration 0008 and change"
                         " tests/test_migrations.py:3 to expect 0008"))
    said, ruled = routed(place, text, start=start)
    assert parks(said, ruled), ruled
    assert "a test the run started with" in said


@pytest.mark.parametrize("rec", [
    "(none)", "<none>", "**none**", "`none`", "None.", "no recommendation",
    "No recommendation; the person must choose", "TBD", "unknown",
    "ask the person", "it is the person's call", "the user's call",
    "N/A (needs the owner)", "nothing to recommend", "nothing", "-", "?",
    "up to the operator", "Either works. The owner decides",
    "should it be 30 or 60 days?",
])
def test_a_recommend_that_holds_no_choice_parks(tmp_path, rec):
    place = a_place(tmp_path)
    text = page(*asking_("What date does `qty` go? The request gives no date",
                         "none", rec))
    said, ruled = routed(place, text)
    assert parks(said, ruled), ruled


@pytest.mark.parametrize("rec", [
    "escape it", "by id", "no; leave /export as it is", "yes",
    "nothing changes for the old path: keep `--curve` as it is",
    "inclusive (`at >= since`)", "nonetheless escape it in one helper",
])
def test_a_recommend_with_a_choice_is_decided(tmp_path, rec):
    place = a_place(tmp_path)
    text = page(*asking_("Is the list sorted by name or by id? docs/api.md:4"
                         " does not say", "none", rec))
    said, ruled = routed(place, text)
    assert said == "" and len(ruled) == 1, said


SPLIT_TEXT = ('the request "reverses the ranking" reads as the whole ranking'
              " reversed, or as the N largest printed smallest first")


@pytest.mark.parametrize("line", [
    "- SPLIT: " + SPLIT_TEXT,
    "* SPLIT: " + SPLIT_TEXT,
    "SPLIT - " + SPLIT_TEXT,
    "SPLIT = " + SPLIT_TEXT,
    "- QUESTION: does it reverse all of it?",
    "- RECOMMEND: reverse the full ranking",
    "SETTLED BY none",
])
def test_a_question_key_the_reader_drops_parks(tmp_path, line):
    place = a_place(tmp_path)
    block = ["QUESTION: does --reverse reverse all of it?", "SETTLED BY: none",
             line, "RECOMMEND: reverse the full ranking", "SIZE: one line"]
    said, ruled = routed(place, page(*block))
    assert parks(said, ruled), (line, ruled)
    assert line.strip() + asking.UNREAD_SAID in said


def test_a_dropped_key_with_no_question_parks_alone(tmp_path):
    place = a_place(tmp_path)
    said, ruled = routed(place, page("- QUESTION: is it sorted by id?"))
    assert said.startswith(asking.UNREAD)
    assert ruled == []


@pytest.mark.parametrize("line", [
    "SPLIT: " + SPLIT_TEXT, "Split: " + SPLIT_TEXT, "**SPLIT**: " + SPLIT_TEXT,
])
def test_a_split_key_the_reader_takes_parks_as_a_split(tmp_path, line):
    place = a_place(tmp_path)
    block = ["QUESTION: does --reverse reverse all of it?", "SETTLED BY: none",
             line, "RECOMMEND: reverse the full ranking", "SIZE: one line"]
    said, ruled = routed(place, page(*block))
    assert parks(said, ruled)
    assert asking.UNREAD_SAID not in said


@pytest.mark.parametrize("mark", [
    "spec: break docs/api.md:2",
    "spec breaks docs/api.md:2",
    "spec: broken docs/api.md:2",
    "spec: violates docs/api.md:2",
    "spec: contradict docs/api.md:2",
    "spec: **breaks** docs/api.md:2",
    "**spec:** breaks docs/api.md:2",
    "spec: docs/api.md:2 allows it",
    "spec: silent",
])
def test_a_spec_line_in_none_of_the_taught_forms_parks(tmp_path, mark):
    place = a_place(tmp_path)
    text = page(*asking_("How is the LF written?", "none", "escape it"))
    text = text.replace("  spec: nothing in the spec", "  " + mark)
    said, ruled = routed(place, text)
    assert parks(said, ruled), (mark, ruled)
    assert mark.lstrip("-").strip() in said


def test_an_unread_spec_line_with_no_question_parks_alone(tmp_path):
    place = a_place(tmp_path)
    text = page().replace("  spec: nothing in the spec",
                          "  spec: break docs/api.md:2")
    said, ruled = routed(place, text)
    assert said.startswith(asking.UNREAD)
    assert "- spec: break docs/api.md:2" in said.split(NL)


@pytest.mark.parametrize("mark", [
    "spec: nothing in the spec", "spec: allows docs/api.md:3",
    "spec: adds to docs/api.md:3", "spec: Nothing in the spec.",
])
def test_a_spec_line_in_a_taught_quiet_form_is_no_mark(tmp_path, mark):
    place = a_place(tmp_path)
    text = page(*asking_("Is the list sorted by id?", "none", "by id"))
    text = text.replace("  spec: nothing in the spec", "  " + mark)
    said, ruled = routed(place, text)
    assert said == "" and len(ruled) == 1, said


def test_prose_that_opens_with_the_word_spec_is_no_mark(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_("Is the list sorted by id?", "none", "by id"))
    text = text.replace("HANDOFF" + NL, "spec coverage is complete here."
                        + NL + "spec-files: none" + NL + "HANDOFF" + NL, 1)
    said, ruled = routed(place, text)
    assert said == "" and len(ruled) == 1, said
