"""the lead's own QUESTION reaches the person only for a risk the program
finds on the page: an unruled `spec: breaks` / `spec: contradicts` mark, a
test the run started with named by the question, its cites or its SETTLED
BY, a typed SPLIT line, or no recommendation. any other question with a
recommendation is the lead's decision, on record for the person to
overrule; SETTLED BY is its recorded reason, never the gate.

the pages are the shapes recorded planner answers took, the lines the
program reads kept word for word but names, dates and paths.
"""
import subprocess
import sys
import types

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import rulings, snapshot
from agentweft.orchestrate import decisions
from agentweft.runner import asking, ruling
from agentweft.runner.handoff import Handoff

NL = chr(10)
LEAD = "planner.md"
SPEC = [
    "# api",
    "- Every command exits 0 on success and 2 on any error. On an error it"
    " prints exactly one line to stderr.",
    "- Fields are separated by commas.",
    '- Every list returns the envelope `{"items": [...], "page": n}`.',
    "- A name is text, and the caf" + chr(0xE9) + " name keeps its accents.",
    "- Never return a bare string as an error.",
]
PIN = ["def test_the_last_migration_is_0007():",
       "    names = ['0001_init', '0007_units']",
       '    assert names[-1].startswith("0007_"), names', ""]
CODE = ["def check(value):",
        '    raise ValueError(f"invalid --curve: {value}")', ""]
CANNED = ("No one is available to answer questions during this run. Make the"
          " call yourself, work in place on the current branch, say which"
          " calls you made, and continue.")
REQUEST = ("Add `top --reverse`: `--reverse` reverses the ranking. Rename an"
           " item with PATCH.")


def a_place(where, git=False):
    where.mkdir(parents=True, exist_ok=True)
    (where / "docs").mkdir(exist_ok=True)
    (where / "tests").mkdir(exist_ok=True)
    (where / "docs" / "api.md").write_text(NL.join(SPEC) + NL,
                                           encoding="utf-8")
    (where / "tests" / "test_migrations.py").write_text(NL.join(PIN),
                                                        encoding="utf-8")
    (where / "cli.py").write_text(NL.join(CODE), encoding="utf-8")
    if git:
        run = ["git", "-C", str(where), "-c", "user.name=a",
               "-c", "user.email=a"]
        subprocess.run(run + ["init", "-q"], check=True)
        subprocess.run(run + ["add", "-A"], check=True)
        subprocess.run(run + ["commit", "-qm", "start"], check=True)
    return where


def page(*blocks):
    return NL.join(["- behaviour: a behaviour of the plan",
                    "  file: cli.py", "  spec: nothing in the spec", "",
                    "HANDOFF", "DID:", "- planned it"] + list(blocks)
                   + ["END HANDOFF"])


def asking_(question, settled, rec, size="one line", split=None):
    out = ["QUESTION: " + question, "SETTLED BY: " + settled]
    if split is not None:
        out.append("SPLIT: " + split)
    return out + ["RECOMMEND: " + rec, "SIZE: " + size]


def a_run(place, kept=None, start=None, held=None, request=REQUEST):
    ruled = []
    run = types.SimpleNamespace(
        workdir=place, lead=LEAD, led={}, start=start,
        spec_line_covered=None, task_text=request, kept=kept,
        rule=lambda decided, why, by: ruled.append((decided, why, by)),
        rulings=lambda: [])
    if held is not None:
        run.spec_line_held = held
    return run, ruled


def routed(place, text, **kw):
    """-> (what goes to the person or "", the rulings the lead wrote)."""
    run, ruled = a_run(place, **kw)
    out = Handoff("planner", text)
    said = asking.lead_escalates(run, LEAD, out)
    if not said:
        asking.lead_decides(run, LEAD, out, "the-run")
    return said, ruled


def kept_of(place, text, **kw):
    """-> what the run's record keeps of the question the page parks on."""
    run, _ = a_run(place, **kw)
    return asking.lead_parks(run, LEAD, Handoff("planner", text))[1]


def canned(place):
    kept = rulings.Kept(place)
    kept.record(ruling.decided(LEAD, CANNED),
                ruling.why(LEAD, "the-park", "NEEDS: an earlier question",
                           CANNED, "the operator"), "answer")
    return kept


def heading(place):
    lines = (place / "decisions.md").read_text(encoding="utf-8").split(NL)
    n = next(i for i, l in enumerate(lines, 1) if decisions.ENTRY.match(l))
    return n, decisions.ENTRY.match(lines[n - 1]).group(1)


def test_a_question_settled_by_an_answer_cited_by_its_stamp_is_decided(
        tmp_path):
    place = a_place(tmp_path)
    kept = canned(place)
    _, stamp = heading(place)
    rec = ("ignore them and change only the name. This matches `create_item`,"
           " and keeps the endpoint a rename. Decided as lead under the"
           " ruling.")
    text = page(*asking_(
        "Are keys other than `name` in a PATCH /items/{id} body ignored or"
        " refused? docs/api.md:4 says nothing about it",
        "decisions.md:" + stamp + ' "' + CANNED + '"', rec))
    said, ruled = routed(place, text, kept=kept)
    assert said == ""
    [(decided, why, by)] = ruled
    assert decided == LEAD + " decided for " + LEAD + ": " + rec
    assert by == rulings.LEAD
    lines = (place / "decisions.md").read_text(encoding="utf-8").split(NL)
    n = lines.index(CANNED) + 1
    assert 'which decisions.md:' + str(n) + ' "' + CANNED + '" settles' in why


def test_a_stamp_cite_with_no_colon_is_read_too(tmp_path):
    place = a_place(tmp_path)
    kept = canned(place)
    _, stamp = heading(place)
    said = asking.answer_settles(
        a_run(place, kept=kept)[0],
        "decisions.md " + stamp + ' "' + CANNED + '"')
    lines = (place / "decisions.md").read_text(encoding="utf-8").split(NL)
    assert said == "decisions.md:" + str(lines.index(CANNED) + 1)


def test_a_question_whose_reason_is_unread_is_decided_and_says_so(tmp_path):
    place = a_place(tmp_path)
    kept = canned(place)
    n, stamp = heading(place)
    rec = ("Both. Add one decision file under docs/decisions/ and one line"
           " under docs/api.md:4")
    text = page(*asking_(
        'Does "record the condition as the decision" mean a file under'
        " docs/decisions/ as well as a line in docs/api.md?",
        "decisions.md:" + str(n) + ' "## ' + stamp + "  ruling for planner.md:"
        ' request: no date"', rec))
    said, ruled = routed(place, text, kept=kept)
    assert said == ""
    [(decided, why, _)] = ruled
    assert decided.endswith(": " + rec)
    assert " settles, and " not in why
    assert "no spec mark, start test or split" in why


def test_a_mark_on_a_line_an_answer_of_the_run_held_does_not_block(tmp_path):
    place = a_place(tmp_path)
    rec = "Ignore it and answer 200 with the envelope."
    text = page(*asking_("Should `GET /items?format=csv` be ignored or refused"
                         " with 400? It turns on docs/api.md:4.",
                         'docs/api.md:4 "' + SPEC[3][2:] + '"', rec))
    text = text.replace("  spec: nothing in the spec",
                        "  spec: contradicts docs/api.md:4 (already ruled)")
    held = [SPEC[3]]
    said, ruled = routed(
        place, text,
        held=lambda rel, line: "an answer" if line in held else None)
    assert said == ""
    assert [d for d, _, _ in ruled] == [LEAD + " decided for " + LEAD + ": "
                                       + rec]


def test_a_question_with_a_recommendation_and_no_risk_is_the_lead_s(
        tmp_path):
    place = a_place(tmp_path)
    recs = ["an entry is `{id, name}` with a required non-empty text name",
            "inclusive (`at >= since`)"]
    text = page(*(asking_("What does a manual entry hold? Nothing in"
                          " docs/api.md:4 describes an entry", "none",
                          recs[0])
                  + asking_("Is a move whose `at` equals `since` included?"
                            " docs/api.md:4 does not say", "none", recs[1])))
    said, ruled = routed(place, text)
    assert said == ""
    assert [d for d, _, _ in ruled] == [LEAD + " decided for " + LEAD + ": "
                                       + r for r in recs]


SIBLING = ('spec: breaks docs/api.md:2, already at cli.py:2 "raise'
           ' ValueError(f"invalid --curve: {value}")"')


def a_sibling_page(plain):
    plan = ["- behaviour: an LF in `--delimiter` prints one stderr line",
            "  file: cli.py", "  spec: breaks docs/api.md:2"] if plain else []
    plan += ["- behaviour: the curve error", "  file: cli.py", "  " + SIBLING,
             "- behaviour: fix: docs/api.md:2 for `--curve`", "  file: cli.py",
             "  " + SIBLING, ""]
    return NL.join(plan + ["HANDOFF", "DID:", "- planned it"] + asking_(
        "How should a value holding LF be written in the error so it stays"
        " one line, as docs/api.md:2 requires?", "none",
        "Write each LF as `\\n` in every echoed option value, in one helper")
        + ["END HANDOFF"])


def test_a_sibling_breach_is_fixed_and_its_how_decided_never_asked(tmp_path):
    for plain in (False, True):
        place = a_place(tmp_path / str(plain))
        run, ruled = a_run(place)
        out = Handoff("planner", a_sibling_page(plain))
        said = asking.lead_escalates(run, LEAD, out)
        assert said == "", said
        assert list(run.adjacent) == [SIBLING]
        asking.lead_decides(run, LEAD, out, "the-run")
        assert [d.split(": ", 1)[1] for d, _, _ in ruled] == [
            "Write each LF as `\\n` in every echoed option value, in one"
            " helper"]


def test_unruled_marks_on_two_lines_park_in_one_stop(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_("May docs/api.md:2 change?", "none", "yes"))
    text = text.replace("  spec: nothing in the spec",
                        "  spec: breaks docs/api.md:2" + NL
                        + "- behaviour: another" + NL + "  file: cli.py" + NL
                        + "  spec: breaks docs/api.md:3")
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: May docs/api.md:2 change?")
    lines = said.split(NL)
    assert "- spec: breaks docs/api.md:2" in lines
    assert "- spec: breaks docs/api.md:3" in lines
    assert ruled == []


def test_a_mark_whose_cite_cannot_be_read_parks(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_("Which code?", "none", "the 400"))
    text = text.replace("  spec: nothing in the spec",
                        "  spec: breaks the error line")
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: Which code?")
    assert "- spec: breaks the error line" in said.split(NL)
    assert ruled == []


PIN_Q = ("should items with another unit become pcs through a new migration"
         " 0008 that rewrites the stored rows, or when they are read?"
         " tests/test_migrations.py:3 pins 0007 as the last migration")
PIN_ID = "tests/test_migrations.py::test_the_last_migration_is_0007"


def test_a_question_on_a_start_test_parks_as_the_test_question(tmp_path):
    for git in (False, True):
        place = a_place(tmp_path / str(git), git=git)
        start = snapshot.take(place) if git else None
        text = page(*asking_(
            PIN_Q, 'tests/test_migrations.py:3 "    assert names[-1]'
            '.startswith("0007_"), names"',
            "convert when reading, with no migration"))
        said, ruled = routed(place, text, start=start)
        assert said.startswith("NEEDS: " + PIN_Q), said
        assert "- " + PIN_ID + " - a test the run started with" \
            in said.split(NL)
        assert any(l.startswith("- override: ") for l in said.split(NL))
        assert kept_of(place, text, start=start) == ruling.edits_asked(
            [PIN_ID, "tests/test_migrations.py"])
        assert ruled == []


@pytest.mark.parametrize("settled", [
    'tests\\test_migrations.py:3 "assert names[-1]"',
    'the request "' + REQUEST[:20] + '" and tests/test_migrations.py'])
def test_a_start_test_named_anywhere_on_the_question_parks(tmp_path,
                                                            settled):
    place = a_place(tmp_path)
    text = page(*asking_("May the pre-existing tests change to expect the new"
                         " key?", settled, "`re-iterate now`. Allow those"
                         " tests to change"))
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: May the pre-existing tests")
    assert "a test the run started with" in said
    assert kept_of(place, text)["tests"]
    assert ruled == []


def test_a_test_file_the_run_did_not_start_with_is_no_test_question(
        tmp_path):
    place = a_place(tmp_path, git=True)
    start = snapshot.take(place)
    (place / "tests" / "test_new.py").write_text("def test_x():" + NL
                                                 + "    assert 1" + NL,
                                                 encoding="utf-8")
    text = page(*asking_("Should tests/test_new.py:2 check the key?", "none",
                         "yes, check the key"))
    said, ruled = routed(place, text, start=start)
    assert said == ""
    assert len(ruled) == 1


REVERSE = ("For `top --reverse`, are equal values in reverse input order or"
           " still in input order? And does `--n` pick the N smallest?")


def test_a_typed_split_of_the_request_s_words_parks(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_(REVERSE, "none", "reverse the full ranking, then"
                         " take the first N", split='the request "reverses'
                         ' the ranking" reads as the whole ranking reversed,'
                         " or as the N largest printed smallest first"))
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: " + REVERSE)
    assert 'SPLIT: the request "reverses the ranking" reads as the whole' \
        " ranking reversed, or as the N largest printed smallest first" \
        " (the quote is in the request)" in said.split(NL)
    assert ruled == []


@pytest.mark.parametrize("split", [
    'the request "reverses all of it" reads as one, or as two',
    'docs/api.md:3 "Fields are separated by commas." reads as one',
    "two readings"])
def test_a_split_line_the_program_cannot_check_still_parks(tmp_path, split):
    place = a_place(tmp_path)
    text = page(*asking_(REVERSE, "none", "reverse the ranking", split=split))
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: " + REVERSE)
    assert "SPLIT: " + split + " (not checked: " in said
    assert ruled == []


def test_a_split_of_one_spec_line_parks(tmp_path):
    place = a_place(tmp_path)
    split = ('docs/api.md:3 "Fields are separated by commas." reads as one'
             " comma, or as any run of commas")
    text = page(*asking_("How are empty fields read?", "none",
                         "one comma each", split=split))
    said, _ = routed(place, text)
    assert "SPLIT: " + split + " (the quote is on docs/api.md:3)" \
        in said.split(NL)


@pytest.mark.parametrize("rec", [
    "The person names a date. Then the worker adds one line under"
    " docs/api.md:4", "none", "None: only you know it"])
def test_an_answer_only_the_person_holds_parks(tmp_path, rec):
    place = a_place(tmp_path)
    text = page(*asking_("What date does `qty` go? The request gives no date",
                         "none", rec))
    said, ruled = routed(place, text)
    assert said.startswith("NEEDS: What date does `qty` go?")
    assert ruled == []


def test_a_recommendation_that_says_no_is_still_one(tmp_path):
    place = a_place(tmp_path)
    text = page(*asking_("Does the export count as stock?", "none",
                         "no; leave /export as it is"))
    said, ruled = routed(place, text)
    assert said == ""
    assert [d.split(": ", 1)[1] for d, _, _ in ruled] == [
        "no; leave /export as it is"]


CACHE_TEST = ["def test_the_list_is_cached():", "    assert 'cached'", ""]


def test_an_override_to_the_test_question_lets_the_named_test_change(
        tmp_path, monkeypatch):
    import test_lead_own_question as own
    from agentweft.runner import engine, manifest, stops

    own.a_flow(tmp_path, monkeypatch)
    (tmp_path / "tests").mkdir()
    test = tmp_path / "tests" / "test_cache.py"
    test.write_text(NL.join(CACHE_TEST), encoding="utf-8")
    ask = "may tests/test_cache.py:2 change to say the list is cleared?"
    own.answering(monkeypatch, own.block(ask, "yes, change it"))
    assert own.run(monkeypatch) == stops.EXIT_STOP
    folder = own.folder(tmp_path)
    test_id = "tests/test_cache.py::test_the_list_is_cached"
    assert manifest.load(folder).data["stopped"]["runner"] == \
        ruling.edits_asked([test_id, "tests/test_cache.py"])

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if step == "worker.md":
            test.write_text(NL.join(CACHE_TEST).replace("cached'",
                                                        "cleared'"),
                            encoding="utf-8")
        return own.block("none") if step == "planner.md" else "done" + NL, \
            False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(sys, "argv", [
        "run.py", "led", "--force", "--resume", folder.name, "--answer",
        "override: the list is cleared on a write now"])
    assert engine.main() == stops.EXIT_OK


@pytest.mark.parametrize("said, cite", [
    ('tests/test_migrations.py:3 "    assert names[-1].startswith("0007_"),'
     ' names"', "tests/test_migrations.py:3"),
    ('docs\\api.md:4 "' + SPEC[3][2:] + '"', "docs/api.md:4"),
    ('docs/api.md:5 "A name is text, and the caf' + chr(0xE9) + ' name"',
     "docs/api.md:5")])
def test_a_settling_cite_reads_inner_quotes_windows_paths_and_accents(
        tmp_path, said, cite):
    place = a_place(tmp_path)
    assert ruling.settles(said, place) == cite
