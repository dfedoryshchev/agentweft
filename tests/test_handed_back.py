"""an answer that hands the call back, and the marks an answer already took.

the person answers the question of a run that waits with `--answer`. in a
flow that names a lead, and only there, the park offers a second form: an
answer that starts `yours:` hands the call back: every later QUESTION of the lead's own
in the run is decided by its RECOMMEND, settled by the line of decisions.md
the hand-back stands on, and listed first on the handoff with those words.
any other answer decides only its own question, whatever its words say. a
hand-back does not lift a mark on a spec line the person was never asked
about, and a question with no RECOMMEND still parks. the step that runs
again is told which marks of its question the answer took.
"""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, stops
from test_lead_own_question import (ASK, NL, REC, a_flow, block, decision,
                                    folder, parks)

NEW = "which status code does a stale read return?"
STALE = "return 200 with the cached body"
YOURS = "yours: make the call yourself"


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


def test_a_new_question_after_a_hand_back_is_the_lead_s_to_decide(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, asked = resumed(tmp_path, monkeypatch, block(NEW, STALE), YOURS)
    assert code == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    entry = decisions.read(tmp_path)[-1]
    assert entry.decided == "planner.md decided for planner.md: " + STALE
    first = decision(folder(tmp_path)).strip().split(NL)
    assert first[0] == "- decided by the lead: " + NEW
    assert first[2] == "  settled by " + answer_cite(tmp_path, YOURS)


def test_an_answer_that_does_not_start_yours_decides_only_its_question(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, asked = resumed(tmp_path, monkeypatch, block(NEW, STALE),
                          "make the call yourself, say which you made")
    assert code == stops.EXIT_STOP
    assert [s for s, _ in asked] == ["planner.md"]


def test_a_hand_back_lifts_no_mark_on_a_line_the_person_was_not_asked_about(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch,
                      block(NEW, STALE, spec="breaks TASK.md:2"), YOURS)
    assert code == stops.EXIT_STOP
    assert "- spec: breaks TASK.md:2" in (
        folder(tmp_path) / "question.md").read_text(
            encoding="utf-8").split(NL)


def test_a_question_with_no_recommendation_parks_after_a_hand_back(
        tmp_path, monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    code, _ = resumed(tmp_path, monkeypatch, block(NEW), YOURS)
    assert code == stops.EXIT_STOP


def test_the_hand_back_settles_questions_on_a_later_leg_too(tmp_path,
                                                           monkeypatch):
    parks(tmp_path, monkeypatch, block(ASK, REC))
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
    parks(tmp_path, monkeypatch, block(ASK, REC))
    _, asked = resumed(tmp_path, monkeypatch, block("none"), YOURS)
    told = " ".join(dict(asked)["planner.md"].split())
    assert "this answer hands the call back" in told
    assert "the marks it lists" not in told


def test_a_park_offers_the_hand_back(tmp_path, monkeypatch, capsys):
    parks(tmp_path, monkeypatch, block(ASK, REC))
    text = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    assert '--answer "yours: <any words>"' in text
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name])
    assert engine.main() == stops.EXIT_STOP
    assert '--answer "yours: <any words>"' in capsys.readouterr().out


def lead_less(tmp_path):
    path = tmp_path / "flows" / "led" / "flow.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "lead: planner", "lead: none"), encoding="utf-8")


def test_a_flow_with_no_lead_offers_no_hand_back(tmp_path, monkeypatch,
                                                 capsys):
    a_flow(tmp_path, monkeypatch)
    lead_less(tmp_path)
    worker = NL.join(["HANDOFF", "DID:", "- built it", "NEEDS: " + ASK,
                      "END HANDOFF", ""])
    from test_lead_own_question import answering, run

    answering(monkeypatch, block("none"), worker)
    assert run(monkeypatch) == stops.EXIT_STOP
    text = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    assert "yours:" not in text and "flow's lead" not in text, text
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name])
    assert engine.main() == stops.EXIT_STOP
    assert "yours:" not in capsys.readouterr().out
    _, asked = resumed(tmp_path, monkeypatch, block("none"), YOURS)
    told = " ".join(dict(asked)["worker.md"].split())
    assert YOURS in told
    assert "hands the call back" not in told


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


def test_a_golden_of_a_flow_with_no_lead_shows_no_hand_back():
    from pathlib import Path

    golden = Path(__file__).resolve().parent / "golden"
    assert "yours:" not in (golden / "fix-with-test" / "ruling-resume.json"
                            ).read_text(encoding="utf-8")
    assert "yours:" in (golden / "build-feature" / "escalated-resume.json"
                        ).read_text(encoding="utf-8")


def test_a_conflict_is_not_handed_back(tmp_path, monkeypatch, capsys):
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
    assert engine.main() == 1
