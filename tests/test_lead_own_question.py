"""a QUESTION the lead's own handoff asks is decided or goes to the person.

the lead is the step that decides what other steps ask. its own QUESTION is
decided by its RECOMMEND only when the context settles it: a `SETTLED BY:
<file>:<line> "<the line>"` line under it names a line of the place and
quotes it as the run found it. the decision is put on record in
decisions.md as the lead's, every later step gets it, and the handoff lists
it first under the one decision. a question no line settles (a gap in the
requirements), one with no RECOMMEND, and every question of a plan that
marks a spec line `spec: breaks` or `spec: contradicts` park the run at the
lead for the person; a `spec: breaks` mark parks it with no question too.
a SETTLED BY line that is empty, names no line of the place, or quotes what
the line does not say settles nothing. `QUESTION: none` asks nothing, and a
QUESTION of a step that is not the lead rides on the handoff as before.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, stops

NL = chr(10)
ASK = "should a write through the client clear the cached list?"
REC = "clear the cached list on a successful write"
SETTLES = 'TASK.md:2 "the list is cached"'
CAFE = "le caf" + chr(0xe9) + " est servi chaud"


def block(question, recommend=None, settled=None, spec="allows TASK.md:2"):
    lines = ["HANDOFF", "DID:", "- set out the cache", "QUESTION: " + question]
    if recommend:
        lines.append("RECOMMEND: " + recommend)
    if settled is not None:
        lines.append("SETTLED BY: " + settled)
    if recommend:
        lines.append("SIZE: 2 lines in api.py")
    return NL.join(["- behaviour: the list is cached", "  file: api.py",
                    "  spec: " + spec, ""] + lines + ["END HANDOFF", ""])


def a_flow(tmp_path, monkeypatch):
    d = tmp_path / "flows" / "led"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(NL.join([
        "name: led", "lead: planner", "steps:", "  - role: planner",
        "    prompt: planner.md", "  - role: worker", "    prompt: worker.md",
        ""]), encoding="utf-8")
    for role in ("planner", "worker"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (tmp_path / "TASK.md").write_text("# task" + NL + "the list is cached"
                                      + NL, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text(
        CAFE + ", et la liste aussi" + NL,
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])


def answering(monkeypatch, planner, worker="done" + NL):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        return (planner if step == "planner.md" else worker), False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force"])
    return engine.main()


def folder(tmp_path):
    runs = sorted((p for p in (tmp_path / "runs").iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime)
    return runs[-1]


def decision(found):
    text = (found / "handoff.md").read_text(encoding="utf-8")
    return text.split("## the one decision")[1].split(NL + "##")[0]


def parks(place, monkeypatch, planner):
    a_flow(place, monkeypatch)
    asked = answering(monkeypatch, planner)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert [s for s, _ in asked] == ["planner.md"]
    assert decisions.read(place) == []
    return (folder(place) / "question.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("settled", [
    SETTLES, 'docs\\api.md:1 "' + CAFE + '"'])
def test_a_lead_question_a_line_of_the_place_settles_is_its_decision(
        tmp_path, monkeypatch, settled):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, block(ASK, REC, settled))
    assert run(monkeypatch) == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    [entry] = decisions.read(tmp_path)
    assert entry.decided == "planner.md decided for planner.md: " + REC
    assert ASK in entry.why
    assert REC in dict(asked)["worker.md"]
    first = decision(folder(tmp_path)).strip().split(NL)
    assert first[0] == "- decided by the lead: " + ASK
    assert REC in first[1]


def test_a_lead_question_no_line_settles_parks(tmp_path, monkeypatch):
    question = parks(tmp_path, monkeypatch, block(ASK, REC))
    assert ASK in question and REC in question


def test_a_lead_question_with_no_recommendation_parks(tmp_path, monkeypatch):
    assert ASK in parks(tmp_path, monkeypatch, block(ASK, None, SETTLES))


@pytest.mark.parametrize("settled", [
    "", "none", "TASK.md:2", "TASK.md:2 the list is cached",
    'TASK.md:9 "the list is cached"', 'TASK.md:2 "the list is never cached"',
    'TASK.md:2 "list"', 'TASK.md:0 "the list is cached"',
    'nowhere.md:1 "the list is cached"', '../TASK.md:2 "the list is cached"',
    'decisions.md:1 "the list is cached"', "the spec says so",
    '"the list is cached"'])
def test_a_settling_line_that_says_nothing_checkable_settles_nothing(
        tmp_path, monkeypatch, settled):
    question = parks(tmp_path, monkeypatch, block(ASK, REC, settled))
    assert ASK in question and REC in question


@pytest.mark.parametrize("spec", ["breaks TASK.md:2", "contradicts TASK.md:2",
                                  "breaks TASK.md:9", "breaks"])
def test_a_question_of_a_plan_that_marks_a_spec_line_parks_with_the_mark(
        tmp_path, monkeypatch, spec):
    question = parks(tmp_path, monkeypatch,
                     block(ASK, REC, SETTLES, spec=spec))
    assert ASK in question and REC in question
    assert "- spec: " + spec in question.split(NL)


def test_a_mark_that_a_spec_line_is_broken_parks_with_no_question(
        tmp_path, monkeypatch):
    question = parks(tmp_path, monkeypatch,
                     block("none", spec="breaks TASK.md:2"))
    assert question.startswith("NEEDS: ")
    assert "- spec: breaks TASK.md:2" in question.split(NL)


@pytest.mark.parametrize("spec", ["breaks TASK.md:2", "allows TASK.md:2"])
def test_a_question_the_person_answered_is_not_asked_again_on_the_resume(
        tmp_path, monkeypatch, spec):
    planner = block(ASK, REC, spec=spec)
    parks(tmp_path, monkeypatch, planner)
    asked = answering(monkeypatch, planner)
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name, "--answer",
                                      "clear it"])
    assert engine.main() == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]


def resumed(tmp_path, monkeypatch, planner, answer="clear it"):
    """-> (the exit code, the steps called) of a resume of the run that
    waits, with `answer`; `planner` is the planner's answer, or a function of the
    place's decisions.md text as the planner is called."""
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        if step != "planner.md":
            return "done" + NL, False
        if callable(planner):
            return planner((tmp_path / decisions.FILE).read_text(
                encoding="utf-8")), False
        return planner, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name, "--answer",
                                      answer])
    return engine.main(), asked


@pytest.mark.parametrize("again", ["breaks TASK.md:2 (answered: clear it)",
                                   "breaks TASK.md:2-2",
                                   "breaks `TASK.md:2` - the cached list"])
def test_an_answered_mark_written_differently_on_the_resume_is_not_asked_again(
        tmp_path, monkeypatch, again):
    parks(tmp_path, monkeypatch, block(ASK, REC, spec="breaks TASK.md:2"))
    code, asked = resumed(tmp_path, monkeypatch, block(ASK, REC, spec=again))
    assert code == stops.EXIT_OK
    assert asked == ["planner.md", "worker.md"]


@pytest.mark.parametrize("again", ["breaks TASK.md:1", "breaks TASK.md:1-2",
                                   "breaks docs/api.md:1", "breaks"])
def test_a_new_or_wider_mark_on_the_resume_still_parks(tmp_path, monkeypatch,
                                                       again):
    parks(tmp_path, monkeypatch, block(ASK, REC, spec="breaks TASK.md:2"))
    code, asked = resumed(tmp_path, monkeypatch, block(ASK, REC, spec=again))
    assert code == stops.EXIT_STOP
    assert asked == ["planner.md"]


def answer_line(text, answer="clear it"):
    """-> the decisions.md line the person's answer stands on, as a cite."""
    lines = text.split(NL)
    n = max(i for i, l in enumerate(lines, 1) if l.strip() == answer)
    return decisions.FILE + ":" + str(n) + ' "' + answer + '"'


REWORDED = ASK.replace("should", "must")


def test_a_reworded_question_the_person_s_answer_settles_is_not_asked_again(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, asked = resumed(tmp_path, monkeypatch, lambda text: block(
        REWORDED, REC, answer_line(text)))
    assert code == stops.EXIT_OK
    assert asked == ["planner.md", "worker.md"]
    first = decision(folder(tmp_path)).strip().split(NL)
    assert first[0] == "- decided by the lead: " + REWORDED


def test_a_reworded_question_that_cites_no_answer_is_asked_again(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch, block(REWORDED, REC))
    assert code == stops.EXIT_STOP


def test_a_new_question_on_the_resume_still_parks(tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch, block(
        "which status code does a stale read return?",
        "return 200 with the cached body"))
    assert code == stops.EXIT_STOP


def test_a_question_extended_with_a_new_clause_still_parks(tmp_path,
                                                           monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch,
                      block(ASK + " (and the detail view?)", REC))
    assert code == stops.EXIT_STOP


@pytest.mark.parametrize("cite", [
    lambda text: answer_line(text).replace('"clear it"', '"clear all"'),
    lambda text: answer_line(text).replace(":", ":1", 1),
    lambda text: decisions.FILE + ':1 "# decisions"',
    lambda text: answer_line(text).replace(decisions.FILE, "TASK.md")])
def test_a_decisions_cite_that_is_not_the_person_s_answer_settles_nothing(
        tmp_path, monkeypatch, cite):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch,
                      lambda text: block(REWORDED, REC, cite(text)))
    assert code == stops.EXIT_STOP


def test_an_answer_given_to_another_run_settles_nothing(tmp_path,
                                                         monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch, block(ASK, REC))
    assert code == stops.EXIT_OK
    text = (tmp_path / decisions.FILE).read_text(encoding="utf-8")
    answering(monkeypatch, block(REWORDED, REC, answer_line(text)))
    assert run(monkeypatch) == stops.EXIT_STOP


def test_a_decisions_cite_of_an_entry_the_lead_wrote_settles_nothing(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    answering(monkeypatch, block(ASK, REC, SETTLES))
    assert run(monkeypatch) == stops.EXIT_OK
    text = (tmp_path / decisions.FILE).read_text(encoding="utf-8")
    n = next(i for i, l in enumerate(text.split(NL), 1) if REC in l)
    answering(monkeypatch, block(REWORDED, REC, decisions.FILE + ":" + str(n)
                                 + ' "' + REC + '"'))
    assert run(monkeypatch) == stops.EXIT_STOP


def test_a_clash_named_only_in_the_question_s_words_parks(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("AGENTWEFT_SPEC_GLOBS", "TASK.md,docs")
    clash = ("TASK.md says the list is never cached, and the request asks"
             " for a cache. build the cache?")
    question = parks(tmp_path, monkeypatch,
                     block(clash, "build the cache the request asks for"))
    assert "build the cache the request asks for" in question


def test_a_lead_question_of_none_asks_nothing(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    asked = answering(monkeypatch, block("none"))
    assert run(monkeypatch) == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    assert decisions.read(tmp_path) == []
    assert "nothing waits on you" in decision(folder(tmp_path))


def test_a_question_of_a_step_that_is_not_the_lead_rides_as_before(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    worker = NL.join(["built it", "", "HANDOFF", "DID:", "- built it",
                      "QUESTION: " + ASK, "RECOMMEND: " + REC,
                      "SIZE: 2 lines in api.py", "END HANDOFF", ""])
    asked = answering(monkeypatch, block("none"), worker)
    assert run(monkeypatch) == stops.EXIT_OK
    assert decisions.read(tmp_path) == []
    assert ASK in decision(folder(tmp_path))


def test_the_planner_is_taught_the_settling_line_and_the_broken_mark(
        monkeypatch):
    from test_spec_addition import composed

    said = composed(monkeypatch, "planner.md")
    taught = 'SETTLED BY: <file>:<line> "<the line, word for word>"'
    assert taught in said and "|" not in taught
    assert "spec: breaks TASK.md:<line>" in said
    assert " ".join(said.split()).count(
        "settled by that answer: give its line in decisions.md as the"
        " SETTLED BY line") == 1


def test_a_conflict_stops_before_the_lead_s_own_question_is_read(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    planner = ('CONFLICT: TASK.md:2 "the list is cached"' + NL
               + "request: never cache the list" + NL + NL
               + block(ASK, REC, SETTLES, spec="contradicts TASK.md:2"))
    asked = answering(monkeypatch, planner)
    assert run(monkeypatch) == stops.exit_code(stops.CONFLICT)
    assert [s for s, _ in asked] == ["planner.md"]
    assert decisions.read(tmp_path) == []
    assert "contradicts" in (folder(tmp_path) / "question.md").read_text(
        encoding="utf-8")
