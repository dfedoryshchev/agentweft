"""a step that did its work with every gate green goes on past a question
whose answer changes no code.

a `NEEDS:` that cites a spec line is a gap a person rules on, so it is never
taken as the step's own call. but when the step changed the place before it
asked, every gate passed on that change, and the answer it recommends
changes no product code, nothing the run has left to do waits on it: the run
goes on through the rest of its steps, and the question waits for the person
as the handoff's one decision, with its recommendation. the gates run once.
a question whose answer needs code, a step whose gates failed and a step
that asked without changing anything still park.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, ruling, stops

from test_no_code_question import (BLOCK, FAIL, NL, a_flow, answering, folder,
                                   gated, run)

GAP = "which code does a request with no date get: 400 or 422?"
CITED = ("NEEDS: " + GAP + NL + "CITES: TASK.md:2" + NL
         + "RECOMMEND: keep 400, the code the check already gives" + NL
         + "SIZE: one doc line" + NL)
CITED_CODE = ("NEEDS: " + GAP + NL + "CITES: TASK.md:2" + NL
              + "RECOMMEND: 422 for a missing date" + NL
              + "SIZE: 3 lines in calc.py" + NL)
WROTE = {"calc.py": "x = 2" + NL}


def decision(found):
    text = (found / "handoff.md").read_text(encoding="utf-8")
    return text.split("## the one decision")[1].split(NL + "##")[0]


def test_a_cited_question_that_changes_no_code_waits_on_a_done_run(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, "fixed it" + NL + CITED + BLOCK,
                      WROTE)
    assert run(monkeypatch) == stops.EXIT_OK
    assert asked == ["a.md", "b.md"]
    found = folder(tmp_path)
    gates = (found / "gates.md").read_text(encoding="utf-8")
    assert gates.count("## a.md") == 1, gates
    assert "PASS command" in gates
    assert "NEEDS: " + GAP in (found / "a.md").read_text(encoding="utf-8")
    said = decision(found)
    assert GAP in said and "keep 400" in said
    assert "a.md did the work with every gate green" in capsys.readouterr().out
    [line] = [json.loads(l) for l in (found / "steps.jsonl").read_text(
        encoding="utf-8").split(NL) if '"step": "a.md"' in l]
    assert line["went_on"] == "NEEDS: " + GAP
    assert not (found / "question.md").exists()


def test_a_cited_question_whose_answer_needs_code_still_parks(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, "fixed it" + NL + CITED_CODE,
                      WROTE)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert asked == ["a.md"]
    assert GAP in (folder(tmp_path) / "question.md").read_text(
        encoding="utf-8")


def test_a_question_after_failed_gates_still_parks(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, gate=FAIL)
    asked = answering(monkeypatch, tmp_path, "fixed it" + NL + CITED, WROTE)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert asked == ["a.md"]
    found = folder(tmp_path)
    assert (found / "gates.md").read_text(encoding="utf-8").count(
        "## a.md") == 1
    text = (found / "handoff.md").read_text(encoding="utf-8")
    assert "its gates ran on what it changed, and failed: command" in text


def test_a_question_from_a_step_that_changed_nothing_still_parks(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, CITED)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert asked == ["a.md"]
    assert not gated(folder(tmp_path))


B_ASKS = ("NEEDS: which file holds the parser?" + NL
          + "RECOMMEND: parse.py" + NL + "SIZE: 3 lines in calc.py" + NL)


def test_a_later_park_shows_its_own_recommendation_and_keeps_the_earlier(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step == "a.md":
            (tmp_path / "calc.py").write_text("x = 2" + NL, encoding="utf-8")
            return "fixed it" + NL + CITED + BLOCK, False
        return "looked" + NL + B_ASKS, False

    monkeypatch.setattr(engine, "call", fake_call)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert asked == ["a.md", "b.md"]
    said = decision(folder(tmp_path))
    stop, _, rest = said.partition("raised by b")
    own, _, also = rest.partition("also open:")
    assert "parse.py" in own and "keep 400" not in own, said
    assert GAP in also and "keep 400" in also, said


def test_which_questions_change_no_code():
    assert ruling.asks_no_code(CITED)
    assert not ruling.asks_no_code(CITED_CODE)
    for said in ("", "fixed it" + NL,
                 "NEEDS: " + GAP + NL + "CITES: TASK.md:2" + NL,
                 "NEEDS: " + GAP + NL + "OPTIONS:" + NL + "- A: 400" + NL
                 + "- B: 422" + NL):
        assert not ruling.asks_no_code(said), said
    for size in ("one doc line", "One doc line.", "no code, 2 doc lines in"
                 " docs/api.md", "zero code lines", "one line in docs/api.md",
                 "two lines in README.md", "a sentence in docs/api.md"):
        assert ruling.asks_no_code(CITED.replace("one doc line", size)), size
    for size in ("one doc line and 2 lines in calc.py", "3 lines in calc.py",
                 "a doc line in src/api.md", "one line in src/api.md",
                 "one line", "one line in docs/api.md and one in calc.py"):
        assert not ruling.asks_no_code(CITED.replace("one doc line", size)), \
            size


# the shapes of two recorded parks after the work was done: a patcher that
# priced its answer as one doc line pinned only if someone wants it, and a
# worker whose answer needs a condition in a code file besides a doc line
DOC_PRICED = ("NEEDS: `{\"delta\": null}`. docs/api.md:42 only says \"400 a bad"
              " request\" and names no code." + NL
              + "RECOMMEND: keep `missing_field`, as the check did before, and"
              " null means \"not given\" here." + NL
              + "SIZE: one line in docs/api.md, if someone wants it pinned." + NL)
CODE_PRICED = ("NEEDS: how an other-class item compares with `below`."
               " docs/conventions.md:16 says it is not decided yet." + NL
               + "RECOMMEND: leave it unpinned until a ruling." + NL
               + "SIZE: one SQL condition in app/db/repo.py and one doc line."
               + NL)


def test_an_answer_priced_as_doc_lines_only_changes_no_code():
    assert ruling.asks_no_code(DOC_PRICED)
    assert not ruling.asks_no_code(CODE_PRICED)


def test_a_question_priced_as_one_line_in_a_doc_waits_on_a_done_run(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, tmp_path, "fixed it" + NL + DOC_PRICED
                      + BLOCK, WROTE)
    assert run(monkeypatch) == stops.EXIT_OK
    assert asked == ["a.md", "b.md"]
    assert "keep `missing_field`" in decision(folder(tmp_path))
