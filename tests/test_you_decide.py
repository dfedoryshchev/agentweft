"""the operator's `you decide` to a run stopped on the lead's own page.

the lead decides in that question's own context, with what the page the run
stopped on recommended as the default: before the lead goes again, every
QUESTION that page asked with a RECOMMEND is put on record as its decision,
under the operator's hand-back, and handed to the lead. a page that now
answers one of them otherwise says so on a typed line,

    DEPARTS: <the question's first words> - <the new answer> - <why>

which goes on record and is listed first on the head. a question with no
RECOMMEND has no default and is the lead's to decide again.

the shape is a recorded one: the page stopped on a split, a second question
recommended "error", and the leg after the hand-back decided "accepted" for
it with no line saying so.
"""
import sys

sys.path.insert(0, ".")
from agentweft.orchestrate import decisions
from agentweft.runner import engine, stops
from test_lead_own_question import NL, a_flow, answering, folder, run

SPLIT_Q = "for a cached list, is the cache one per client or one shared?"
SPLIT_REC = "one cache per client"
SPLIT_LINE = ('SPLIT: TASK.md:2 "the list is cached" reads as one cache per'
              " client, or as one shared cache")
TIME_Q = "is a time outside the years 0001 to 9999 an invalid time?"
TIME_REC = "error: invalid time"
TIME_LEG = "accepted and compared as an instant"
BYTES_Q = "does a size with leading zeros print as written?"
BYTES_REC = "print the integer"
HAND_BACK = "you decide"


def page(*questions, extra=()):
    lines = ["- behaviour: the list is cached", "  file: api.py",
             "  spec: allows TASK.md:2", "", "HANDOFF", "DID:",
             "- set out the cache"]
    for q in questions:
        lines.append("QUESTION: " + q[0])
        if q[1]:
            lines.append("RECOMMEND: " + q[1])
            lines.append("SIZE: 2 lines in api.py")
        lines.extend(q[2:])
    lines.extend(extra)
    return NL.join(lines + ["END HANDOFF", ""])


STOPPED = page((SPLIT_Q, SPLIT_REC, SPLIT_LINE), (TIME_Q, TIME_REC),
               (BYTES_Q, BYTES_REC))


def stopped(tmp_path, monkeypatch, planner=STOPPED):
    a_flow(tmp_path, monkeypatch)
    answering(monkeypatch, planner)
    assert run(monkeypatch) == stops.EXIT_STOP
    assert decisions.read(tmp_path) == []


def resumed(tmp_path, monkeypatch, planner, answer=HAND_BACK):
    asked = []
    at_call = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append((step, prompt))
        at_call.append(len(decisions.read(tmp_path)))
        return (planner if step == "planner.md" else "done" + NL), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(sys, "argv", ["run.py", "led", "--force", "--resume",
                                      folder(tmp_path).name, "--answer",
                                      answer])
    return engine.main(), asked, at_call


def led(tmp_path):
    return {d.decided.split(": ", 1)[1]: d for d in decisions.read(tmp_path)
            if d.decided.startswith("planner.md decided for planner.md: ")}


def head(tmp_path):
    text = (folder(tmp_path) / "handoff.md").read_text(encoding="utf-8")
    return text.split("## the one decision")[1].split(NL + "##")[0]


def test_every_recommendation_it_stopped_on_is_on_record_before_the_lead_goes(
        tmp_path, monkeypatch):
    stopped(tmp_path, monkeypatch)
    leg = page((TIME_Q, TIME_LEG), (BYTES_Q, BYTES_REC))
    code, asked, at_call = resumed(tmp_path, monkeypatch, leg)
    assert code == stops.EXIT_OK
    assert [s for s, _ in asked] == ["planner.md", "worker.md"]
    decided = led(tmp_path)
    assert set(decided) == {SPLIT_REC, TIME_REC, BYTES_REC}
    assert TIME_LEG not in decided
    # the answer, then the three, all before the planner's go
    assert at_call[0] == 4
    planner = " ".join(asked[0][1].split())
    for rec in (SPLIT_REC, TIME_REC, BYTES_REC):
        assert rec in planner
    for d in decided.values():
        assert "under the operator's hand-back" in d.why, d.why


def test_the_head_says_each_was_decided_under_the_hand_back(tmp_path,
                                                            monkeypatch):
    stopped(tmp_path, monkeypatch)
    resumed(tmp_path, monkeypatch, page((TIME_Q, TIME_REC)))
    lines = head(tmp_path).strip().split(NL)
    assert "- decided under the operator's hand-back: " + TIME_Q in lines
    assert "- decided by the lead: " + TIME_Q not in lines


def test_a_departure_on_a_typed_line_goes_on_record_and_is_listed_first(
        tmp_path, monkeypatch):
    stopped(tmp_path, monkeypatch)
    leg = page((TIME_Q, TIME_LEG), extra=[
        "DEPARTS: is a time outside the years - " + TIME_LEG
        + " - the request names no limit for it"])
    code, _, _ = resumed(tmp_path, monkeypatch, leg)
    assert code == stops.EXIT_OK
    departed = [d for d in decisions.read(tmp_path)
                if d.decided.startswith("planner.md departs for planner.md: ")]
    assert len(departed) == 1
    assert TIME_LEG in departed[0].decided
    assert TIME_REC in departed[0].why
    assert "the request names no limit for it" in departed[0].why
    lines = head(tmp_path).strip().split(NL)
    assert lines[0] == ("- departs from the recommendation it stopped on: "
                        + TIME_Q)
    assert TIME_LEG in lines[1]


def test_a_departure_naming_a_start_test_goes_up_as_the_test_question(
        tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_times.py").write_text(
        "def test_years():" + NL + "    assert True" + NL, encoding="utf-8")
    stopped(tmp_path, monkeypatch)
    leg = page((TIME_Q, TIME_LEG), extra=[
        "DEPARTS: is a time outside the years - " + TIME_LEG
        + " - tests/test_times.py::test_years goes to the new range"])
    code, asked, _ = resumed(tmp_path, monkeypatch, leg)
    assert code == stops.EXIT_STOP
    assert [s for s, _ in asked] == ["planner.md"]
    assert not [d for d in decisions.read(tmp_path) if d.decided.startswith(
        "planner.md departs for planner.md: ")]
    said = (folder(tmp_path) / "question.md").read_text(encoding="utf-8")
    assert TIME_Q in said
    assert "- tests/test_times.py - a test the run started with" in said
    assert "RECOMMEND: " + TIME_LEG in said


def test_a_departs_line_that_names_no_question_it_had_is_not_a_departure(
        tmp_path, monkeypatch, capsys):
    stopped(tmp_path, monkeypatch)
    leg = page((TIME_Q, TIME_REC), extra=[
        "DEPARTS: something never asked - x - y"])
    code, _, _ = resumed(tmp_path, monkeypatch, leg)
    assert code == stops.EXIT_OK
    assert not [d for d in decisions.read(tmp_path)
                if " departs for " in d.decided]
    assert "DEPARTS line names no question" in capsys.readouterr().out


def test_a_departs_line_out_of_its_form_is_not_a_departure(tmp_path,
                                                           monkeypatch):
    stopped(tmp_path, monkeypatch)
    leg = page((TIME_Q, TIME_REC), extra=["DEPARTS: is a time outside"])
    code, _, _ = resumed(tmp_path, monkeypatch, leg)
    assert code == stops.EXIT_OK
    assert not [d for d in decisions.read(tmp_path)
                if " departs for " in d.decided]


def test_the_lead_is_told_its_answers_stand_and_how_to_depart(
        tmp_path, monkeypatch):
    stopped(tmp_path, monkeypatch)
    _, asked, _ = resumed(tmp_path, monkeypatch, page((TIME_Q, TIME_REC)))
    told = " ".join(asked[0][1].split())
    assert "DEPARTS: <the question's first words> - <the new answer> -" \
        " <why>" in told


def test_a_question_with_no_recommendation_gets_no_default(
        tmp_path, monkeypatch):
    stopped(tmp_path, monkeypatch, page((SPLIT_Q, "none"), (TIME_Q, TIME_REC)))
    code, _, _ = resumed(tmp_path, monkeypatch, page((TIME_Q, TIME_REC)))
    assert code == stops.EXIT_OK
    assert set(led(tmp_path)) == {TIME_REC}


def test_an_answer_that_is_no_hand_back_records_no_recommendation(
        tmp_path, monkeypatch):
    stopped(tmp_path, monkeypatch)
    code, _, at_call = resumed(tmp_path, monkeypatch, page((BYTES_Q, BYTES_REC)),
                               answer="one shared cache")
    assert at_call[0] == 1
    assert TIME_REC not in led(tmp_path)


def test_a_hand_back_to_a_step_that_is_not_the_lead_records_nothing(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    worker = NL.join(["HANDOFF", "DID:", "- built it", "NEEDS: " + TIME_Q,
                      "END HANDOFF", ""])
    answering(monkeypatch, page((BYTES_Q, BYTES_REC)), worker)
    assert run(monkeypatch) == stops.EXIT_STOP
    before = len(decisions.read(tmp_path))
    code, _, at_call = resumed(tmp_path, monkeypatch, page((BYTES_Q, BYTES_REC)))
    assert at_call[0] == before + 1
