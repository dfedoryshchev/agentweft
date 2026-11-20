"""the lead may ask an architect or a business analyst role one typed
question about its own QUESTION, and the answer is read for risks before
the lead decides.

the question is read for every risk first, so one that names a start test,
sits beside an unruled spec mark, carries a SPLIT line or a line the runner
cannot read never reaches a consult. a consult's typed RISK line other than
`none` parks the question; one in no taught form, two of them, none, an
empty answer or one that changed a file parks it too. with `RISK: none` the
lead goes once more and its final page is read as any lead page is; a
`from:` line on its line is the reason recorded beside the decision. the
shipped build-feature flow, on canned answers and a real pytest in a git
repo.
"""
import json
import sys
import types

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import rulings
from agentweft.runner import asking, stops

try:
    from agentweft.runner import consult
except ImportError:
    consult = None

import test_lead as tl

NL = chr(10)
ARCH = "architect.md"
START_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
              + "    assert add(2, 1) == 3" + NL)


def plan(*lines, extra=()):
    return NL.join([tl.PLAN.rstrip(NL)] + list(extra)
                   + ["", "HANDOFF", "DID:", "- planned mul in calc.py"]
                   + list(lines) + ["END HANDOFF"]) + NL


def question(rec="none", consult_line="architect does mul keep a float"
             " product as it is", settled="none",
             asked="should mul keep a float product as it is, which"
             " TASK.md:3 leaves open?", more=()):
    out = ["QUESTION: " + asked, "SETTLED BY: " + settled]
    out += list(more)
    out += ["RECOMMEND: " + rec]
    if consult_line is not None:
        out.append("CONSULT: " + consult_line)
    return out + ["SIZE: none"]


ASKS = plan(*question())
DECIDES = plan(*question(rec="keep: return the product as it is",
                         consult_line=None))
NO_RISK = ("FOUND: calc keeps what the spec says, a times b" + NL
           + 'from: TASK.md:3 "mul(a, b) returns a times b"' + NL
           + "RISK: none" + NL)


def build(tmp_path, monkeypatch, planner, architect, writes=None,
          start=()):
    answers = {"planner.md": list(planner), "tester.md": [tl.TESTER],
               "worker.md": [tl.WORKER], "reviewer.md": [tl.OK],
               "reviewer-runs.md": [tl.OK], ARCH: list(architect)}
    wrote = {"tester.md": [("tests/test_mul.py", tl.TEST)],
             "worker.md": [("calc.py", tl.AFTER)]}
    wrote.update(writes or {})
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, wrote,
                     start=start)


def lines_of(folder):
    return [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]


def decisions_of(project):
    path = project / "decisions.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_a_consult_with_no_risk_hands_the_lead_a_checked_cite_and_it_decides(
        tmp_path, monkeypatch):
    asked, sent, code, folder, project = build(
        tmp_path, monkeypatch, [ASKS, DECIDES], [NO_RISK])
    assert asked[:3] == ["planner.md", ARCH, "planner.md"]
    assert code == 0
    told = sent[2]
    assert "CONSULTED. you asked the architect" in told
    assert 'TASK.md:3 "mul(a, b) returns a times b"' in told
    handed = sent[1]
    assert "CONSULT: architect does mul keep a float product" in handed
    assert '- TASK.md:3 "mul(a, b) returns a times b"' in handed
    assert "you decide nothing" in handed
    said = decisions_of(project)
    assert "after asking the architect, which TASK.md:3" in said
    consulted = [l for l in lines_of(folder) if l["step"] == ARCH]
    assert [l["won"] for l in consulted] == ["cite"]


def test_a_consult_that_names_a_start_test_parks_and_the_lead_goes_no_more(
        tmp_path, monkeypatch):
    risk = ("FOUND: a test pins add" + NL
            + "RISK: test tests/test_add.py::test_add" + NL)
    asked, _, code, folder, project = build(
        tmp_path, monkeypatch, [ASKS, DECIDES], [risk],
        start=[("tests/test_add.py", START_TEST)])
    assert asked == ["planner.md", ARCH]
    assert code == stops.EXIT_STOP
    q = (folder / "question.md").read_text(encoding="utf-8")
    assert "found by the architect: RISK: test tests/test_add.py::test_add" \
        in q
    assert "a test the run started with" in q
    consulted = [l for l in lines_of(folder) if l["step"] == ARCH]
    assert [l["won"] for l in consulted] == ["evidence"]
    assert "decided" not in decisions_of(project)


@pytest.mark.parametrize("page", [
    plan(*question(asked="may tests/test_add.py:5 change for mul?")),
    plan(*question(), extra=["  spec: breaks TASK.md:3"]),
    plan(*question(more=['SPLIT: the request "calc gets mul(a, b)" reads as'
                         " ints only, or as floats too"])),
    plan(*question(rec="the operator names a date")),
    plan(*question(more=["- RECOMMEND - keep it"])),
], ids=["start test", "spec mark", "split", "person only", "unread line"])
def test_a_question_holding_evidence_never_reaches_a_consult(
        tmp_path, monkeypatch, page):
    asked, _, code, folder, _ = build(
        tmp_path, monkeypatch, [page, DECIDES], [NO_RISK],
        start=[("tests/test_add.py", START_TEST)])
    assert ARCH not in asked
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP


def test_no_recommendation_and_no_consult_line_parks_as_before(
        tmp_path, monkeypatch):
    asked, _, code, _, _ = build(
        tmp_path, monkeypatch, [plan(*question(consult_line=None))],
        [NO_RISK])
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP


@pytest.mark.parametrize("said", [
    "FOUND: x" + NL + "RISK: none" + NL + "RISK: none" + NL,
    "FOUND: x" + NL + "- RISK - none" + NL,
    "FOUND: x" + NL,
    "FOUND: x" + NL + "RISK: maybe the cache" + NL,
    "RISK: person the date the operator wants" + NL,
    'RISK: spec TASK.md:3 "mul(a, b) returns a times b"' + NL,
    'RISK: split the request "calc gets mul(a, b)" reads as ints, or as'
    " floats" + NL,
    "",
], ids=["two risk lines", "off form", "no risk line", "untaught risk",
        "person", "spec", "split", "empty"])
def test_a_consult_answer_that_holds_a_risk_or_cannot_be_read_parks(
        tmp_path, monkeypatch, said):
    asked, _, code, folder, _ = build(
        tmp_path, monkeypatch, [ASKS, DECIDES], [said])
    assert asked == ["planner.md", ARCH]
    assert code == stops.EXIT_STOP
    assert (folder / "question.md").is_file()


def test_a_consult_that_changes_a_file_parks(tmp_path, monkeypatch):
    asked, _, code, folder, _ = build(
        tmp_path, monkeypatch, [ASKS, DECIDES], [NO_RISK],
        writes={ARCH: [("calc.py", tl.AFTER)]})
    assert asked == ["planner.md", ARCH]
    assert code == stops.EXIT_STOP
    [line] = [l for l in lines_of(folder) if l["step"] == ARCH]
    assert "changed a file" in (line["why"] or "")


def test_a_from_line_not_on_its_line_is_dropped_and_said(tmp_path,
                                                          monkeypatch):
    said = ("FOUND: x" + NL + 'from: TASK.md:3 "mul(a, b) returns a sum"' + NL
            + "RISK: none" + NL)
    asked, sent, code, folder, project = build(
        tmp_path, monkeypatch, [ASKS, DECIDES], [said])
    assert code == 0
    assert 'not found there, dropped: TASK.md:3 "mul(a, b) returns a sum"' \
        in sent[2]
    assert 'which TASK.md:3 "' not in decisions_of(project)
    assert [l["won"] for l in lines_of(folder) if l["step"] == ARCH] == [
        "none"]


def test_a_consult_that_would_answer_otherwise_goes_on_record_never_parks(
        tmp_path, monkeypatch):
    page = plan(*question(rec="keep: return the product as it is"))
    said = NO_RISK + "AGREES: no round it to an int" + NL
    asked, sent, code, _, project = build(
        tmp_path, monkeypatch, [page, DECIDES], [said])
    assert code == 0
    assert "AGREES: yes, or AGREES: no" in sent[1]
    assert "the architect would answer otherwise: round it to an int" in \
        decisions_of(project)


def test_a_second_go_that_leaves_the_question_out_parks(tmp_path,
                                                        monkeypatch):
    asked, _, code, folder, _ = build(
        tmp_path, monkeypatch, [ASKS, tl.PLAN], [NO_RISK])
    assert asked == ["planner.md", ARCH, "planner.md"]
    assert code == stops.EXIT_STOP
    assert "left the question out" in (folder / "question.md").read_text(
        encoding="utf-8")


def test_a_lead_still_unsure_after_the_consult_parks(tmp_path, monkeypatch):
    asked, _, code, _, _ = build(
        tmp_path, monkeypatch, [ASKS, ASKS], [NO_RISK])
    assert asked == ["planner.md", ARCH, "planner.md"]
    assert code == stops.EXIT_STOP


def a_run(tmp_path, cap, consulted=()):
    return types.SimpleNamespace(
        fm={"consults": cap}, lead="planner.md", led={}, start=None,
        workdir=str(tmp_path), spec_line_covered=None, task_text="t",
        kept=None, consulted=set(consulted), rule=lambda *a, **k: None,
        rulings=lambda: [])


def lead_page(text):
    from agentweft.runner.handoff import Handoff

    return Handoff("planner", text)


def test_with_consults_0_or_the_cap_spent_no_consult_is_called(tmp_path):
    (tmp_path / "TASK.md").write_text(tl.SPEC, encoding="utf-8")
    page = lead_page(ASKS)
    assert consult.before(a_run(tmp_path, 2), "planner.md", page)
    assert consult.before(a_run(tmp_path, 0), "planner.md", page) == []
    spent = a_run(tmp_path, 2, consulted={"a", "b"})
    assert consult.before(spent, "planner.md", page) == []
    once = a_run(tmp_path, 2, consulted={
        "needs: should mul keep a float product as it is, which tasK.md:3"
        " leaves open?".lower()})
    assert consult.before(once, "planner.md", page) == []


def test_a_from_line_by_a_windows_path_on_a_non_ascii_line_is_checked(
        tmp_path):
    (tmp_path / "docs").mkdir()
    line = "a name keeps its caf" + chr(0xE9) + " accent"
    (tmp_path / "docs" / "names.md").write_text("# names" + NL + NL + line
                                                + NL, encoding="utf-8")
    run = a_run(tmp_path, 2)
    found = consult.read(run, "FOUND: x" + NL + "from: docs\\names.md:3 \""
                         + line + "\"" + NL + "RISK: none" + NL)
    assert found["risk"] == ("none", "")
    assert [c for c, _ in found["froms"]] == ["docs/names.md:3"]
    found = consult.read(run, "RISK: spec docs\\names.md:3 \"" + line + "\"")
    assert found["risk"][0] == "spec"


def test_the_questions_consulted_on_are_on_the_runs_record_and_carried(
        tmp_path):
    first = rulings.Kept(tmp_path)
    first.keep_in(tmp_path / "leg1")
    asking.keep_state(types.SimpleNamespace(kept=first,
                                            consulted={"needs: a"}))
    second = rulings.Kept(tmp_path)
    second.carry(tmp_path / "leg1")
    again = types.SimpleNamespace(kept=second)
    asking.carry_state(again)
    assert again.consulted == {"needs: a"}


def test_a_consult_line_is_a_key_the_lead_is_taught_and_its_off_forms_park():
    text = (tl.FLOWS / "build-feature" / "planner.md").read_text(
        encoding="utf-8")
    assert "`CONSULT: architect <the one thing you need>`" in " ".join(
        text.split())
    off = NL.join(["HANDOFF", "DID:", "- x", "QUESTION: q?",
                   "- CONSULT: architect a", "END HANDOFF"])
    assert asking.unread_asking(off) == ["- CONSULT: architect a"]
