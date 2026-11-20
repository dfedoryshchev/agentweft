"""an answer that hands the call back, and the marks an answer already took.

the operator answers the question of a run that waits with `--answer`. in a
flow that names a lead, and only there, the park offers a second form: an
answer that opens with `you decide` (or, as answers given before read, the
older `yours:`) hands the call back: a later QUESTION of the
lead's own decided with no other reason names the line of decisions.md the
hand-back stands on, and is listed first on the handoff with those words.
any other answer is the reason of no question but its own, whatever its
words say. a hand-back does not lift a mark on a spec line the operator was
never asked about, and a question with no RECOMMEND still parks. the step
that runs again is told which marks of its question the answer took.
"""
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, stops
from test_lead_own_question import (ASK, NL, NO_REASON, PARK, REC, a_flow,
                                    block, decision, folder, parks)

NEW = "which status code does a stale read return?"
STALE = "return 200 with the cached body"
YOURS = "you decide: make the call yourself"
OLD_WORD = "yours: make the call yourself"
YOU_DECIDE = '--answer "you decide"'


def resumed(tmp_path, monkeypatch, planner, answer):
    """-> (the exit code, [(step, prompt)] of the calls) of a resume of the
    run that waits, with `answer`."""
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        return (planner if step == "planner.md" else "done" + NL), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name, "--answer",
                                      answer])
    return engine.main(), asked


def answer_cite(tmp_path, answer):
    lines = (tmp_path / decisions.FILE).read_text(encoding="utf-8").split(NL)
    n = max(i for i, l in enumerate(lines, 1) if l == answer)
    return decisions.FILE + ":" + str(n) + ' "' + answer + '"'


@pytest.mark.parametrize("answer", [YOURS, "You decide.", OLD_WORD])
def test_a_new_question_after_a_hand_back_is_the_lead_s_to_decide(
        tmp_path, monkeypatch, answer):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    code, asked = resumed(tmp_path, monkeypatch, block(NEW, STALE), answer)
    assert code == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    entry = decisions.read(tmp_path)[-1]
    assert entry.decided == "planner.md decided for planner.md: " + STALE
    first = decision(folder(tmp_path)).strip().split(NL)
    assert first[0] == "- decided under the operator's hand-back: " + NEW
    assert first[2] == "  settled by " + answer_cite(tmp_path, answer)


def test_an_answer_that_does_not_start_yours_is_no_reason_for_a_new_question(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    code, asked = resumed(tmp_path, monkeypatch, block(NEW, STALE),
                          "make the call yourself, say which you made")
    assert code == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    assert NO_REASON in decisions.read(tmp_path)[-1].why


def test_a_hand_back_lifts_no_mark_on_a_line_the_person_was_not_asked_about(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    code, _ = resumed(tmp_path, monkeypatch,
                      block(NEW, STALE, spec="breaks TASK.md:2"), YOURS)
    assert code == stops.EXIT_STOP
    assert "- spec: breaks TASK.md:2" in (
        folder(tmp_path) / "question.md").read_text(
            encoding="utf-8").split(NL)


def test_a_question_with_no_recommendation_parks_after_a_hand_back(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    code, _ = resumed(tmp_path, monkeypatch, block(NEW), YOURS)
    assert code == stops.EXIT_STOP


def test_the_hand_back_settles_questions_on_a_later_leg_too(tmp_path,
                                                           monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    code, _ = resumed(tmp_path, monkeypatch, block(NEW), YOURS)
    assert code == stops.EXIT_STOP
    code, asked = resumed(tmp_path, monkeypatch,
                          block("does a write clear the detail view?",
                                "clear it too"), "return 200")
    assert code == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]


def test_the_step_that_runs_again_is_told_the_marks_its_answer_took(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC, spec="breaks TASK.md:2"))
    _, asked = resumed(tmp_path, monkeypatch, block("none"), "clear it")
    told = " ".join(dict(asked)["planner.md"].split())
    assert ("the marks it lists are answered by it: spec: breaks TASK.md:2."
            in told), told
    assert "hands the call back" not in told


def test_the_step_that_runs_again_is_told_it_has_the_call(tmp_path,
                                                          monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    _, asked = resumed(tmp_path, monkeypatch, block("none"), YOURS)
    told = " ".join(dict(asked)["planner.md"].split())
    assert "this answer hands the call back" in told
    assert "the marks it lists" not in told


def test_a_park_offers_the_hand_back(tmp_path, monkeypatch, capsys):
    parks(tmp_path, monkeypatch, block(ASK, PARK))
    text = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    assert YOU_DECIDE in text and "yours" not in text
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name])
    assert engine.main() == stops.EXIT_STOP
    said = capsys.readouterr().out
    assert YOU_DECIDE in said and "yours" not in said


def lead_less(tmp_path):
    path = tmp_path / "flows" / "led" / "flow.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "lead: planner", "lead: none"), encoding="utf-8")


def test_a_flow_with_no_lead_offers_no_hand_back_and_one_given_decides_nothing(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    lead_less(tmp_path)
    worker = NL.join(["HANDOFF", "DID:", "- built it", "NEEDS: " + ASK,
                      "END HANDOFF", ""])
    from test_lead_own_question import answering, run

    answering(monkeypatch, block("none"), worker)
    assert run(monkeypatch) == stops.EXIT_STOP
    text = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    assert YOU_DECIDE not in text and "flow's lead" not in text, text
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name])
    assert engine.main() == stops.EXIT_STOP
    assert YOU_DECIDE not in capsys.readouterr().out
    legs = len(list((tmp_path / "runs").iterdir()))
    code, asked = resumed(tmp_path, monkeypatch, block("none"), YOURS)
    assert code == stops.EXIT_STOP
    assert asked == []
    assert len(list((tmp_path / "runs").iterdir())) == legs
    said = capsys.readouterr().out
    assert "this flow names no lead to decide it" in said
    assert ASK in said
    assert decisions.read(tmp_path) == []


def test_only_the_lead_is_told_the_lead_decides_its_later_questions():
    from agentweft.runner import ruling

    alone = ruling.told("NEEDS: which code?", YOURS)
    worker = ruling.told("NEEDS: which code?", YOURS, lead="planner",
                         step="worker")
    lead = ruling.told("QUESTION: which code?", YOURS, lead="planner",
                       step="planner")
    assert "hands the call back" not in alone
    assert "make it yourself" in worker
    assert "QUESTION of the flow's lead" not in worker
    assert "every later QUESTION of the flow's lead" in lead


def test_an_answer_starting_yours_with_its_own_words_hands_back_and_shows_them():
    from agentweft.runner import ruling

    answer = "Yours: return 304, never 200"
    assert ruling.handed_back(answer)
    told = ruling.told("QUESTION: which code?", answer, lead="planner",
                       step="planner")
    assert "\n\n" + answer + "\n\n" in told
    assert "every later QUESTION of the flow's lead" in told


def test_a_golden_of_a_flow_with_no_lead_shows_no_hand_back():
    from pathlib import Path

    golden = Path(__file__).resolve().parent / "golden"
    assert YOU_DECIDE.replace('"', '\\"') not in (
        golden / "code-review" / "ruling.json").read_text(encoding="utf-8")
    assert YOU_DECIDE.replace('"', '\\"') in (
        golden / "fix-with-test" / "ruling-resume.json").read_text(
            encoding="utf-8")
    assert YOU_DECIDE.replace('"', '\\"') in (
        golden / "build-feature" / "escalated-resume.json").read_text(
            encoding="utf-8")


def test_a_conflict_handed_back_stays_parked_when_the_lead_picks_neither(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch)
    planner = ('CONFLICT: TASK.md:2 "the list is cached"' + NL
               + "request: never cache the list" + NL)
    monkeypatch.setattr(engine, "call", lambda prompt, timeout=None, cap=3,
                        step="?", provider=None: (planner, False))
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force"])
    assert engine.main() == stops.exit_code(stops.CONFLICT)
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name, "--answer",
                                      YOURS])
    capsys.readouterr()
    assert engine.main() == stops.exit_code(stops.CONFLICT)
    assert "picked neither of the park's answers" in capsys.readouterr().out
    assert decisions.read(tmp_path) == []
