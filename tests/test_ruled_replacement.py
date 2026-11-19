"""under an `override:`, another spec line may change by the same replacement
the ruled lines made.

the request renames a word in code spans (`qty` to `quantity`); the person's
`override:` lets the cited lines change. a spec line that only restates the
renamed word, in a file the ruling did not name, is then not a second
question: a plan mark on it is folded under the ruling, and the spec-files
check lets it change when its new text is exactly the old one with the word
replaced, the way the ruled lines changed. each such line is listed under the
ruling, and the head says first that the contract its readers rely on
changed. anything more than that replacement keeps its own question.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import specfiles
from agentweft.orchestrate import decisions
from agentweft.runner import ruling, stops

from test_spec_conflict import RETRO, a_place, end, folders, go, plain

NL = chr(10)
GLOBS = "docs/*.md"
ITEM_LINE = "- an item returns `name` and `qty`."
ENTRY_LINE = "- in each entry `qty` is an integer."
BODY_LINE = "- a request body takes `qty`."
API = "# api" + NL + NL + ITEM_LINE + NL + ENTRY_LINE + NL + BODY_LINE + NL
LABELS = "| labels | `GET /items/{id}` | `name`, `qty` |"
AUDIT = "| audit | `GET /moves` | `at` |"
CONSUMERS = ("# consumers" + NL + NL + LABELS + NL + AUDIT + NL)
ITEMS = 'def item():' + NL + '    return {"name": "a", "qty": 1}' + NL
RENAMED = 'def item():' + NL + '    return {"name": "a", "quantity": 1}' + NL
BASELINE = ("from items import item" + NL + NL + NL + "def test_name():" + NL
            + '    assert item()["name"] == "a"' + NL)
QUANTITY_TEST = ("from items import item" + NL + NL + NL
                 + "def test_quantity():" + NL
                 + '    assert item()["quantity"] == 1' + NL)
REQUEST = ("Rename `qty` to `quantity` in every item the API returns. Request"
           " bodies keep `qty` for now. Update docs/api.md.")
OVERRIDE = ("override: yes; the docs are the spec and change with the code:"
            " those lines may change to match this request, and nothing"
            " else.")


def conflict(cite, quote):
    return 'CONFLICT: ' + cite + ' "' + quote + '"' + NL + "request: " \
        + REQUEST + NL


FIRST = conflict("docs/api.md:3", ITEM_LINE) + conflict("docs/api.md:4",
                                                         ENTRY_LINE)


def second(line=3):
    return NL.join([
        "- behaviour: item() returns `quantity`",
        "  file: items.py",
        "  spec: contradicts docs/api.md:3",
        "- behaviour: the labels consumer reads `quantity`",
        "  file: docs/consumers.md",
        "  spec: breaks docs/consumers.md:" + str(line), "",
        "HANDOFF", "DID:", "- planned it",
        "QUESTION: docs/consumers.md:" + str(line) + " names the field the"
        " rename removes. May it change to `quantity`?",
        "SETTLED BY: none",
        "RECOMMEND: let it say `quantity` and tell the labels owners",
        "SIZE: one doc line", "END HANDOFF"])


TESTER = ("FAILS: KeyError: 'quantity'" + NL + "TEST: tests/test_quantity.py"
          + NL)
BUILT = ("- items.py: quantity" + NL + "- docs/api.md: quantity" + NL
         + "- docs/consumers.md: quantity" + NL)
REVIEWED = "VERDICT: ok" + NL + NL + "- the change" + NL


def renamed(text, more=""):
    return text.replace("`qty`", "`quantity`").replace(BODY_LINE.replace(
        "`qty`", "`quantity`"), BODY_LINE) + more


def edits_of(place, labels=None):
    def edits(step, n):
        if step == "tester.md":
            (place / "tests" / "test_quantity.py").write_text(
                QUANTITY_TEST, encoding="utf-8")
        if step == "worker.md":
            (place / "items.py").write_text(RENAMED, encoding="utf-8")
            (place / "docs" / "api.md").write_text(renamed(API),
                                                   encoding="utf-8")
            text = renamed(CONSUMERS) if labels is None else \
                CONSUMERS.replace(LABELS, labels)
            (place / "docs" / "consumers.md").write_text(text,
                                                         encoding="utf-8")
    return edits


def two_legs(tmp_path, monkeypatch, plan=None, labels=None):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", GLOBS)
    a_place(tmp_path / "project", {
        "docs/api.md": API, "docs/consumers.md": CONSUMERS,
        "items.py": ITEMS, "conftest.py": "",
        "tests/test_items.py": BASELINE})
    place = tmp_path / "project"
    asked, _, code = go(tmp_path, monkeypatch, "build-feature",
                        plain({"planner.md": [FIRST]}), lambda s, n: None,
                        "--task", REQUEST)
    assert (asked, code) == (["planner.md"], stops.EXIT_STOP)
    [leg] = folders(tmp_path)
    answers = plain({"planner.md": [plan or second()], "tester.md": [TESTER],
                     "worker.md": [BUILT], "reviewer.md": [REVIEWED],
                     "reviewer-runs.md": [REVIEWED]})
    return go(tmp_path, monkeypatch, "build-feature", answers,
              edits_of(place, labels), "--resume", leg.name, "--answer",
              OVERRIDE)


def stamp_of(tmp_path):
    [ruled] = [d for d in decisions.read(tmp_path / "project")
               if ": override:" in d.decided]
    return ruled.at.strftime(stops.STAMP) + " " + ruled.decided


def test_a_line_restating_the_ruled_rename_changes_by_it_under_the_ruling(
        tmp_path, monkeypatch):
    asked, _, code = two_legs(tmp_path, monkeypatch)
    assert end(tmp_path).cause != stops.PARKED
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "reviewer-runs.md", RETRO]
    assert code == stops.EXIT_OK
    handoff = (folders(tmp_path)[-1] / "handoff.md").read_text(
        encoding="utf-8")
    stamp = stamp_of(tmp_path)
    assert "docs/consumers.md:3 (ruling " + stamp + "; the same replacement" \
        " `qty` to `quantity` as the ruled lines)" in handoff
    decision = handoff.split("## the one decision" + NL, 1)[1]
    assert decision.startswith(
        "- the consumer contract changed: docs/consumers.md:3 changed by the"
        " replacement `qty` to `quantity` the ruled lines made, under the"
        " ruling of " + stamp)
    assert "- spec docs/consumers.md +1 -1 <- ruling " + stamp in handoff


def test_a_line_changed_beyond_the_replacement_keeps_its_question(
        tmp_path, monkeypatch):
    _, _, code = two_legs(
        tmp_path, monkeypatch,
        labels="| labels | `GET /items/{id}` | `name`, `quantity`, `unit` |")
    assert end(tmp_path).cause == stops.PARKED
    assert code == stops.EXIT_STOP
    question = (folders(tmp_path)[-1] / "question.md").read_text(
        encoding="utf-8")
    assert "- docs/consumers.md:3 - was \"" + LABELS + "\"" in question


def test_a_mark_on_a_line_that_does_not_hold_the_renamed_word_parks(
        tmp_path, monkeypatch):
    asked, _, code = two_legs(tmp_path, monkeypatch, plan=second(line=4))
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP
    assert end(tmp_path).cause == stops.PARKED


@pytest.mark.parametrize("was, now, pair", [
    (ITEM_LINE, renamed(ITEM_LINE), ("qty", "quantity")),
    ("`qty` and qty, not qty_text", "`quantity` and quantity, not qty_text",
     ("qty", "quantity")),
    (ITEM_LINE, ITEM_LINE, None),
    (ITEM_LINE, renamed(ITEM_LINE, " now"), None),
    ("`qty` and `unit`", "`quantity` and `units`", None),
    ("a qty", "a qty b", None),
    ("caf" + chr(0xE9) + " qty", "caf" + chr(0xE9) + " quantity",
     ("qty", "quantity"))])
def test_the_replacement_a_line_made_is_one_word_for_another(was, now, pair):
    assert ruling.replacement(was, now) == pair


@pytest.mark.parametrize("request_, pairs", [
    (REQUEST, [("qty", "quantity")]),
    ("rename `a` to `b` and `c` to `d`", [("a", "b"), ("c", "d")]),
    ("make `qty` bigger", []),
    ("rename `qty-x` to `quantity`", []),
    ("", [])])
def test_a_rename_is_read_from_the_request_s_code_spans(request_, pairs):
    assert ruling.renames(request_) == pairs


def test_the_lines_a_replacement_let_change_are_read_back_from_the_check():
    stamp = "2026-11-19 10:01 ruling for planner.md: override: yes (all; of it)"
    line = specfiles.passed(
        [("docs/api.md", API, renamed(API)),
         ("docs/consumers.md", CONSUMERS, renamed(CONSUMERS))],
        [("docs/api.md", 3, stamp + "; docs/api.md named to change by the"
          " request"),
         ("docs/consumers.md", 3, stamp + "; "
          + specfiles.same_replacement("qty", "quantity")),
         ("docs\\" + chr(0x430) + ".md", 7, stamp + "; "
          + specfiles.same_replacement("qty", "quantity"))])
    assert specfiles.replaced_lines(line.detail) == [
        (stamp, "qty", "quantity",
         ["docs/consumers.md:3", "docs\\" + chr(0x430) + ".md:7"])]
    assert specfiles.replaced_lines("") == []


def test_a_word_is_replaced_only_where_it_stands_alone():
    assert ruling.replaced("qty, `qty` qty_text totalQty", "qty",
                           "quantity") == \
        "quantity, `quantity` qty_text totalQty"
