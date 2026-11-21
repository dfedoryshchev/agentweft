"""the handoff reads what the run's own record shows, not what a step said.

a not verified line on one of three standard checks (the suite not run, a
test's red without the change not shown, its green with the change not
shown) opens with its taught key, and a gate of the run that did that check
answers it: the head drops it and the full record names the gate. the
console's red-first line prints the classes the head prints. the tests line
counts tests added to files the run started with apart from tests it changed
there. a test file the run wrote is never a pre-existing one. "left" names no
step that ran: the one the run stopped at says it runs again. an item a later
step argued shows that step's recommendation, and the first raiser's beside
it when they differ. each decision the lead took names the rung that took it.
"""
import datetime
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails.gates.base import Result
from agentweft.orchestrate import decisions, park
from agentweft.runner import front, gating, handoff, lead, summary

NO_GIT = {"git": False}
NL = chr(10)
NEW = "tests/test_stats.py::test_stats_mean_half_rounds_up"
SUITE = "python -m pytest -q"


def a_pass(step, said, outcome="ok", gates=()):
    return summary.a_pass(step, step[:-3], 1.0, handoff.parse(said),
                          list(gates), False, outcome, said)


def block(did, not_verified=(), doubts=(), question=None):
    out = ["HANDOFF", "DID:", "- " + did]
    if not_verified:
        out += ["NOT VERIFIED:"] + ["- " + i for i in not_verified]
    if doubts:
        out += ["DOUBTS:"] + ["- " + i for i in doubts]
    if question:
        out += ["QUESTION: " + question[0], "RECOMMEND: " + question[1],
                "SIZE: " + question[2]]
    return NL.join(out + ["END HANDOFF", ""])


def command(ok=True):
    return {"gate": "command", "ok": ok, "command": SUITE,
            "detail": "exit 0" if ok else "exit 1: 1 failed"}


def red_first(*tests):
    return {"gate": "red-first", "ok": True, "command": SUITE + " {test}",
            "detail": str(len(tests)) + " of " + str(len(tests)) + " new"
            " tests red without the fix and green with it: "
            + ", ".join(tests),
            "tests": [{"test": t, "before": "red", "kind": "assertion",
                       "after": "green"} for t in tests]}


def build(passes, decided=(), proof=None, changes=NO_GIT, stopped=None,
          needs=None):
    return summary.build("f-1", "f", "fix the rounding", passes, changes,
                         list(decided), "1 call", proof=proof,
                         stopped=stopped, needs=needs)


def section(lines, name):
    text = NL + NL.join(lines)
    if NL + "## " + name + NL not in text:
        return ""
    return text.split(NL + "## " + name + NL, 1)[1].split(NL + "## ")[0]


def head(lines):
    return lines[:lines.index("## full record")]


SUITE_LEFT = "suite not run: this step only needs the new test to fail"
RED_LEFT = "red without the change not shown: " + NEW + " - not run here"
GREEN_LEFT = "green with the change not shown: " + NEW + " - not run here"


def test_a_suite_line_a_later_command_gate_answered_leaves_the_head():
    lines = build([a_pass("worker.md", block("wrote the test", [SUITE_LEFT])),
                   a_pass("patcher.md", block("fixed it"),
                          gates=[command()])])
    assert "suite not run" not in section(head(lines), "not done")
    assert ("- worker: " + SUITE_LEFT + " - answered by the command gate on"
            " patcher.md, pass 2 of the run: exit 0 (" + SUITE + ")") \
        in section(lines, "not verified")


def test_the_suite_line_stays_open_when_the_last_command_gate_failed():
    lines = build([a_pass("worker.md", block("wrote the test", [SUITE_LEFT])),
                   a_pass("patcher.md", block("fixed it"), gates=[command()]),
                   a_pass("patcher.md", block("fixed it again"),
                          gates=[command(False)])])
    assert "suite not run" in section(head(lines), "not done")
    assert "answered by" not in section(lines, "not verified")


def test_a_gate_before_the_step_that_said_it_answers_nothing():
    lines = build([a_pass("worker.md", block("ran it"), gates=[command()]),
                   a_pass("patcher.md", block("fixed", [SUITE_LEFT]))])
    assert "suite not run" in section(head(lines), "not done")


def test_red_and_green_lines_are_answered_by_the_red_first_record_of_that_test():
    lines = build([a_pass("patcher.md", block("fixed it", [RED_LEFT,
                                                           GREEN_LEFT]),
                          gates=[red_first(NEW)])])
    full = section(lines, "not verified")
    assert ("- patcher: " + RED_LEFT + " - answered by the red-first gate on"
            " patcher.md, pass 1 of the run: " + NEW + " red without the"
            " change") in full, full
    assert ("- patcher: " + GREEN_LEFT + " - answered by the red-first gate"
            " on patcher.md, pass 1 of the run: " + NEW + " green with the"
            " change") in full, full
    assert NEW not in section(head(lines), "not done")


def test_a_red_line_on_a_test_the_gate_did_not_run_stays_open():
    other = "tests/test_stats.py::test_other"
    lines = build([a_pass("patcher.md", block("fixed it", [
        "red without the change not shown: " + other + " - not run"]),
        gates=[red_first(NEW)])])
    assert other in section(head(lines), "not done")


SAME_NAME = "tests/test_report.py::test_stats_mean_half_rounds_up"


@pytest.mark.parametrize("key", ["red without the change not shown: ",
                                 "green with the change not shown: "])
@pytest.mark.parametrize("named", [
    SAME_NAME,
    NEW + " and " + SAME_NAME,
    NEW + "[1]",
    "tests/test_report.py",
], ids=["same name in another file", "one of two in another file",
        "a case the replay did not run alone", "another file"])
def test_a_line_on_a_test_the_replay_did_not_run_by_its_whole_id_stays_open(
        key, named):
    lines = build([a_pass("patcher.md", block("fixed it", [
        key + named + " - not run"]), gates=[red_first(NEW + "[2]")])])
    assert "answered by" not in section(lines, "not verified")
    assert named in section(head(lines), "not done")


@pytest.mark.parametrize("named", [
    NEW, ".\\tests\\test_stats.py::test_stats_mean_half_rounds_up",
    "./" + NEW, "test_stats_mean_half_rounds_up", "tests\\test_stats.py"])
def test_a_red_line_on_the_replayed_test_by_its_id_or_bare_name_is_answered(
        named):
    lines = build([a_pass("patcher.md", block("fixed it", [
        "red without the change not shown: " + named + " - not run"]),
        gates=[red_first(NEW)])])
    assert "answered by the red-first gate" in section(lines, "not verified")


@pytest.mark.parametrize("calls", ["stats.py", "src\\stats.py",
                                   "pkg/caf" + chr(0xE9) + ".py"])
def test_a_product_file_named_beside_the_replayed_test_holds_nothing_open(
        calls):
    lines = build([a_pass("patcher.md", block("fixed it", [
        "red without the change not shown: " + NEW + ", which calls " + calls
        + " - not run"]), gates=[red_first(NEW)])])
    assert "answered by the red-first gate" in section(lines, "not verified")


@pytest.mark.parametrize("key,shown", [
    ("red without the change not shown: ", "before"),
    ("green with the change not shown: ", "after")])
def test_a_line_naming_a_test_file_needs_every_test_replayed_in_it_shown(
        key, shown):
    replay = red_first(NEW, "tests/test_stats.py::test_other")
    replay["tests"][1][shown] = "error"
    lines = build([a_pass("patcher.md", block("fixed it", [
        key + "tests/test_stats.py - not run"]), gates=[replay])])
    assert "answered by" not in section(lines, "not verified")
    lines = build([a_pass("patcher.md", block("fixed it", [
        key + "tests/test_stats.py - not run"]), gates=[
            red_first(NEW, "tests/test_stats.py::test_other")])])
    assert "answered by the red-first gate" in section(lines, "not verified")


def test_the_keys_are_read_as_typed_never_from_words():
    said = ["The full suite on the current code - not run",
            "suite not run - no colon after the key",
            "a suite not run: the key is not where the line opens"]
    lines = build([a_pass("worker.md", block("wrote it", said)),
                   a_pass("patcher.md", block("fixed"), gates=[command()])])
    assert "answered by" not in section(lines, "not verified")
    for item in said:
        assert "- worker: " + item + NL in section(lines, "not verified")


def test_the_keys_are_taught_in_the_handoff_template():
    from agentweft.roles import resolver

    taught = (resolver.HERE / "fragments" / "handoff.md").read_text(
        encoding="utf-8")
    for key in ("suite not run:", "red without the change not shown:",
                "green with the change not shown:"):
        assert key in taught, key
    assert "|" not in taught.split("NOT VERIFIED:")[1].split("ASSUMED:")[0]


def test_the_console_prints_the_classes_the_head_prints():
    r = Result("red-first", True, "7 of 7 new tests red without the fix and"
               " green with it: " + NEW)
    r.tests = [{"test": NEW, "before": "red", "kind": "assertion",
                "after": "green"}]
    proof = {"how": "gate", "gate": "red-test", "step": "worker.md",
             "source": "supplied", "ids": [],
             "tests": {"tests/test_bug_report.py": "0"}}
    said = gating.printed(r, proof)
    assert said == ("PASS red-first - 0 written first (the supplied test is"
                    " the proof: tests/test_bug_report.py); 1 added after"
                    " green (coverage); each test is in gates.md"), said
    assert gating.printed(r, None) == repr(r)
    assert gating.printed(Result("command", True, "exit 0"), proof) \
        == "PASS command - exit 0"


def test_the_tests_line_counts_changed_tests_apart_from_new_ones():
    assert summary.tests_line({"test_ids": {
        "tests/test_import.py": ["tests/test_import.py::test_a",
                                 "tests/test_import.py::test_b",
                                 "tests/test_import.py::test_old"],
        "tests/test_new.py": ["tests/test_new.py::test_c"]},
        "tests_new": ["tests/test_new.py"],
        "tests_edited": {"tests/test_import.py":
                         ["tests/test_import.py::test_old"]}}) == (
        "tests: added 2 to files the run started with / added 1 in new"
        " files / changed 1 the run started with / in files"
        " tests/test_import.py, tests/test_new.py.")


def git(place, *args):
    subprocess.run(["git", "-C", str(place), "-c", "user.name=t", "-c",
                    "user.email=t", "-c", "commit.gpgsign=false"]
                   + list(args), check=True, capture_output=True)


def test_a_test_file_the_run_wrote_and_committed_is_not_pre_existing(
        tmp_path):
    place = tmp_path / "place"
    (place / "tests").mkdir(parents=True)
    (place / "tests" / "test_old.py").write_text(
        "def test_one():" + NL + "    assert 1" + NL, encoding="utf-8")
    git(place, "init", "-q")
    git(place, "add", "-A")
    git(place, "commit", "-qm", "start")
    tree = summary.Tree(place)
    (place / "tests" / "test_top.py").write_text(
        "def test_top():" + NL + "    assert 1" + NL, encoding="utf-8")
    with open(place / "tests" / "test_old.py", "a", encoding="utf-8") as f:
        f.write("def test_two():" + NL + "    assert 1" + NL)
    git(place, "add", "-A")
    git(place, "commit", "-qm", "tests first")
    changes = tree.changes()
    said = summary.rulings(changes, [])
    assert "- pre-existing test tests/test_old.py +2 -0, add-only, no ruling" \
        " needed" in said, said
    assert not any("test_top.py" in s for s in said), said
    assert summary.tests_line(changes) == (
        "tests: added 1 to files the run started with / added 1 in new"
        " files / changed 0 the run started with / in files"
        " tests/test_old.py, tests/test_top.py.")


@pytest.mark.parametrize("committed", [False, True])
def test_a_changed_start_test_with_a_non_ascii_name_is_pre_existing(
        tmp_path, committed):
    place = tmp_path / "place"
    (place / "tests").mkdir(parents=True)
    name = "tests/test_caf" + chr(0xE9) + ".py"
    (place / name).write_text("def test_one():" + NL + "    assert 1 == 1"
                              + NL, encoding="utf-8")
    git(place, "init", "-q")
    git(place, "add", "-A")
    git(place, "commit", "-qm", "start")
    tree = summary.Tree(place)
    (place / name).write_text("def test_one():" + NL + "    assert True" + NL,
                              encoding="utf-8")
    if committed:
        git(place, "commit", "-qam", "loosened")
    changes = tree.changes()
    assert [p for p, _, _ in changes["tests_changed"]] == [name], \
        changes["files"]


def test_left_names_no_step_that_ran_and_the_stopped_step_runs_again():
    lines = park.lines("planner.md", None, [("planner.md", 38.6)],
                       ["planner.md", "tester.md", "worker.md"],
                       "python run.py f --resume f-1",
                       question="NEEDS: which holds?", conflict=True)
    left = lines[lines.index("left") + 1:]
    left = left[:left.index("")]
    assert left == ["  tester.md", "  worker.md"], left
    assert park.left_of(lines) == ["tester.md", "worker.md"]
    assert any("planner.md runs again" in l for l in lines)
    said = summary.left_undone({"at": "planner.md", "cause": "conflict"},
                               lines, NO_GIT)
    assert said == ("not done: the run stopped at planner.md, which runs"
                    " again when carried on; left to run after it:"
                    " tester.md, worker.md"), said


def test_a_one_step_flow_left_with_nothing_after_the_stop():
    lines = park.lines("worker.md", None, [("worker.md", 3.0)],
                       ["worker.md"], "python run.py f --resume f-1",
                       question="NEEDS: which holds?", conflict=True)
    assert park.left_of(lines) == []


def test_a_step_that_never_ran_is_still_left():
    lines = park.lines("tester.md", "user", [("planner.md", 1.0)],
                       ["tester.md", "worker.md"],
                       "python run.py f --resume f-1", handed="planner.md")
    assert park.left_of(lines) == ["tester.md", "worker.md"]


ASKED = "When C is CR or LF, what does the error print?"


def test_the_latest_step_that_argued_an_item_gives_its_recommendation():
    lines = build([
        a_pass("tester.md", block("wrote tests", question=(
            ASKED + " TASK.md:11 says one line", "Print C as is",
            "one line"))),
        a_pass("worker.md", block("built it", doubts=[
            '"' + ASKED + '" - my answer: print it escaped, `\\n`'])),
        a_pass("reviewer.md", block("reviewed", doubts=[
            '"' + ASKED + '": I agree with the worker: escape it']))])
    decision = section(head(lines), "the one decision")
    assert ("  recommendation (reviewer, the latest step that argued it):"
            " I agree with the worker: escape it") in decision, decision
    assert "  tester's recommendation: Print C as is (size: one line)" \
        in decision, decision


def test_an_item_no_later_step_argued_keeps_its_raiser_s_recommendation():
    lines = build([
        a_pass("tester.md", block("wrote tests", question=(
            ASKED + " TASK.md:11 says one line", "Print C as is",
            "one line"))),
        a_pass("worker.md", block("built it", doubts=[
            "CR or LF might need escaping somewhere else"]))])
    decision = section(head(lines), "the one decision")
    assert "  recommendation: Print C as is (size: one line)" in decision
    assert "latest step" not in decision


def lead_decision(why, decided="reject it", step="planner.md", heading=None):
    title, body = lead.recorded(step, step, "f-1", "NEEDS: " + ASKED, decided,
                                why)
    return decisions.Decision(heading or title, body,
                              at=datetime.datetime(2026, 1, 1))


def rung_of(lines):
    decision = section(head(lines), "the one decision").split(NL)
    return [l for l in decision if l.startswith("  rung: ")]


def test_a_lead_decision_names_its_rung():
    plain = lead_decision(
        "the recommendation of planner.md's own handoff; no spec mark, start"
        " test or split on it goes to the operator, so planner.md"
        + lead.SETTLES_END)
    assert rung_of(build([], [plain])) == [
        "  rung: the lead, planner.md, on a question of its own page"]
    asked = lead_decision(
        "the recommendation of planner.md's own handoff after asking the"
        " architect (the architect would answer otherwise: keep it), which"
        ' TASK.md:3 "one line"' + lead.SETTLES + "planner.md"
        + lead.SETTLES_END)
    assert rung_of(build([], [asked])) == [
        "  rung: the lead, planner.md, after asking the architect, who would"
        " answer otherwise: keep it"]
    handed = lead_decision(
        "the recommendation of planner.md's handoff the run stopped on"
        + lead.HANDED + ', which decisions.md:4 "you decide"' + lead.SETTLES
        + "planner.md" + lead.SETTLES_END)
    assert rung_of(build([], [handed])) == [
        "  rung: the operator's you decide, then the lead, planner.md, took"
        " the recommendation the run stopped on"]
    title, body = lead.departed("planner.md", "f-1", "NEEDS: " + ASKED,
                                "reject it", "accept it", "the code reads so",
                                'decisions.md:4 "you decide"')
    departs = decisions.Decision(title, body,
                                 at=datetime.datetime(2026, 1, 1))
    assert rung_of(build([], [departs])) == [
        "  rung: the operator's you decide, then the lead, planner.md,"
        " departed from the recommendation the run stopped on"]


def test_the_rung_line_sits_under_its_decision_and_is_never_cut():
    ruled = lead_decision(
        "the recommendation of planner.md's own handoff; no spec mark, start"
        " test or split on it goes to the operator, so planner.md"
        + lead.SETTLES_END)
    decision = section(head(build([], [ruled])), "the one decision").split(NL)
    assert decision[0] == front.LED + ASKED
    assert decision[1].startswith("  its decision: reject it")
    assert decision[2].startswith("  rung: ")
