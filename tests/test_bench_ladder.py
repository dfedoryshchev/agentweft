"""a handoff is scored on a ten-point ladder, one named line per point, by a
program. the strict 0-3 score is 3 on every run now, so it tells nothing
apart; the ladder tells a 6 from a 9, per path.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.bench import __main__ as bench
from agentweft.bench import ladder
from agentweft.runner import front, stops

HERE = Path(__file__).parent / "ladder"
DONE = (HERE / "done-fix.md").read_text(encoding="utf-8")
ESCALATED = (HERE / "lead-escalated.md").read_text(encoding="utf-8")


def got(scored):
    return dict((p["point"], p["got"]) for p in scored["points"])


def test_a_done_fix_with_the_alternatives_outside_why_scores_nine():
    scored = ladder.score(DONE)
    assert scored["path"] == ladder.DONE
    assert scored["score"] == 9
    assert [p for p, g in got(scored).items() if g == 0] == ["why"]


def test_a_park_showing_the_askers_recommendation_over_the_leads_scores_six():
    scored = ladder.score(ESCALATED)
    assert scored["path"] == ladder.PARKED
    assert scored["score"] == 6
    assert sorted(p for p, g in got(scored).items() if g == 0) == [
        "decision", "not_done", "once", "why"]
    line = [p for p in scored["points"] if p["point"] == "decision"][0]["line"]
    assert "planner" in line


def test_every_point_is_a_named_line_in_order():
    out = ladder.lines(ladder.score(DONE))
    named = [l for l in out if l.startswith("  ") and ":" in l]
    assert [l.split(":")[0].strip() for l in named] == [
        str(n + 1) + " " + name for n, (_, name) in enumerate(ladder.POINTS)]
    assert out[0].endswith("done, 9/10")


def stop_with_no_tests():
    head = ("# build-feature build-feature-1: stopped: spec conflict at"
            " planner.md - TASK.md:4 says ids are numbers")
    return "\n".join([
        head, "", "build-feature ran planner.md in 3s on: ids.",
        "suite: no gates ran; red first: not proven by a gate.",
        "changed: nothing in the tree, 0 commits (from git, below).",
        "", "## the one decision",
        "- TASK.md:4 says ids are numbers, the request asks for names",
        "  raised by planner; cites TASK.md:4",
        "  recommendation: keep the spec. (size: none)",
        "", "## why", "planner did:", "- read the spec and found the clash",
        "", "## not done", "- not done: nothing was changed; the request"
        " waits on the clash", "", "## product gaps", "- TASK.md:4",
        "", "## needs you", "to carry on",
        "  python run.py build-feature --resume build-feature-1 --answer x",
        "", "## assumed - tell me if wrong", "- nothing assumed, or no step"
        " said", "", "## doubts", "- none raised", "", "## changed",
        "- nothing changed in the tree", "- git status --short: prints"
        " nothing", "", "## read", "- planner.md read: TASK.md (whole file)",
        "  said: TASK.md:4 - ids are numbers", "", "## tests and checks",
        "- planner.md: no gates", "- red first: not proven by a gate", "",
        "## rulings", "- none on record in decisions.md", "", "## run",
        "- cause: conflict at planner.md", ""])


def test_a_point_the_path_has_no_line_for_is_not_applicable_never_zero():
    scored = ladder.score(stop_with_no_tests())
    assert scored["path"] == ladder.STOPPED
    assert got(scored)["tests"] is None
    assert got(scored)["checks"] is None
    assert scored["applicable"] == 8
    assert scored["score"] == 10


def a_stop_decision(cause, rec=None):
    word = stops.outcome(cause)
    head = "# demo demo-1: " + word + " at worker.md - it stopped"
    return "\n".join(
        [head, "", "## the one decision", "- " + word + " at worker.md - it"
         " stopped", "  " + front.CARRY]
        + (["  recommendation: " + rec] if rec else [])
        + ["", "## not done", "- not done: the run stopped at worker.md",
           "", "## run", "- cause: " + cause + " at worker.md", "",
           "to carry on", "  python run.py demo --resume demo-1"])


def test_a_stop_that_is_its_own_decision_holds_it_with_its_carry_on_line():
    for cause in (stops.GATE, stops.EXCEPTION, stops.OVERLAP):
        assert got(ladder.score(a_stop_decision(cause)))["decision"] == 1, \
            cause


def test_a_stop_whose_cause_names_what_to_do_needs_the_recommendation():
    for cause in (stops.BUDGET, stops.OUTAGE, stops.INTERRUPT):
        assert got(ladder.score(a_stop_decision(cause)))["decision"] == 0, \
            cause
        assert got(ladder.score(a_stop_decision(cause, "carry on")))[
            "decision"] == 1, cause


ORDER_RULED = ("- on record: 2026-01-05 21:40 planner.md decided for worker.md:"
               " Leave the order among invalid option values unspecified."
               " Keep the order `_check_options` already uses: `--scale`,"
               " then `--sep`.")
ORDER_OPEN = ("- When `--sep` and `--scale` are all invalid, which error is"
              " reported? TASK.md:23 only says option values come first\n"
              "  raised by planner, worker; cites TASK.md:23\n"
              "  recommendation: keep the order the code already has")
NEWLINE_OPEN = ("- Should an LF `--sep` print a raw newline in `error: invalid"
                " --sep: <C>`, giving two stderr lines against TASK.md:11, or"
                " print it escaped?\n"
                "  raised by tester, worker; cites TASK.md:11\n"
                "  recommendation: keep it raw, as the request words it")


def ruled_open(question, ruling):
    return got(ladder.score(DONE.replace(
        "- none: nothing waits on you.", question).replace(
        "- none on record in decisions.md", ruling)))


def test_the_question_a_ruling_decided_shown_open_on_a_done_run_is_false():
    marks = ruled_open(ORDER_OPEN, ORDER_RULED)
    assert marks["decision"] == 0
    assert marks["no_false"] == 0


def test_a_ruling_on_another_question_leaves_the_open_one_standing():
    marks = ruled_open(NEWLINE_OPEN, ORDER_RULED)
    assert marks["decision"] == 1
    assert marks["no_false"] == 1


def test_a_ruling_citing_the_open_questions_line_decided_it():
    marks = ruled_open(NEWLINE_OPEN, "- on record: 2026-01-05 21:40 planner.md"
                       " decided for worker.md: print it raw, as TASK.md:11"
                       " reads")
    assert marks["decision"] == 0
    assert marks["no_false"] == 0


def test_a_cut_question_is_matched_on_its_full_text_in_open_questions():
    cut = ("- When both are given at once and `--s...\n"
           "  raised by planner; cites TASK.md:24\n"
           "  recommendation: keep the order the code already has")
    text = DONE.replace("- none: nothing waits on you.", cut).replace(
        "- none on record in decisions.md", ORDER_RULED)
    assert got(ladder.score(text))["no_false"] == 1
    text = text.replace(
        "## doubts", "## open questions\n- planner: When both are given at"
        " once and `--sep` and `--scale` are all invalid, which error is"
        " reported? TASK.md:23 only says option values come first"
        " (recommendation: keep the order)\n\n## doubts", 1)
    assert got(ladder.score(text))["no_false"] == 0


def test_an_unbacked_verified_line_loses_checks_backed():
    text = DONE.replace("saw: 38 passed in 5.26s -> backed",
                        "saw: 38 passed -> unbacked: no such command in the"
                        " step's transcript")
    assert got(ladder.score(text))["checks"] == 0


def test_a_verified_line_that_quotes_nothing_it_ran_loses_checks_backed():
    text = DONE.replace("saw: 38 passed in 5.26s -> backed",
                        "-> ran: nothing of its output quoted")
    scored = ladder.score(text)
    assert got(scored)["checks"] == 0
    line = [p for p in scored["points"] if p["point"] == "checks"][0]["line"]
    assert "ran" in line


def no_gates(text):
    return "\n".join(l for l in text.split("\n")
                     if not (l.startswith("- ") and (": PASS " in l
                                                     or ": FAIL " in l)))


def test_verified_lines_nothing_checked_are_not_applicable_never_held():
    text = no_gates(DONE).replace("-> backed", "-> unchecked: no transcript"
                                  " for this step")
    scored = ladder.score(text)
    assert got(scored)["checks"] is None
    line = [p for p in scored["points"] if p["point"] == "checks"][0]["line"]
    assert "2 verified lines unchecked" in line


def test_an_unchecked_line_beside_backed_ones_is_counted_apart():
    text = DONE.replace("saw: 38 passed in 5.26s -> backed",
                        "saw: 38 passed in 5.26s -> unchecked: no transcript"
                        " for this step")
    scored = ladder.score(text)
    assert got(scored)["checks"] == 1
    line = [p for p in scored["points"] if p["point"] == "checks"][0]["line"]
    assert "1 verified line backed" in line and "1 unchecked" in line


def test_a_done_word_on_a_tree_the_hidden_suite_finds_red_is_not_true():
    assert got(ladder.score(DONE, correct=False))["outcome"] == 0
    assert got(ladder.score(DONE, correct=True))["outcome"] == 1


def outcome_point(scored):
    return [p for p in scored["points"] if p["point"] == "outcome"][0]


def test_with_no_hidden_verdict_point_one_is_named_consistent_not_true():
    assert outcome_point(ladder.score(DONE))["name"] == "outcome consistent"
    assert outcome_point(ladder.score(DONE, correct=True))["name"] == \
        "outcome true"
    assert outcome_point(ladder.score(DONE, correct=False))["name"] == \
        "outcome true"


def test_score_run_passes_the_hidden_verdict_through(tmp_path):
    (tmp_path / "handoff.md").write_text(DONE, encoding="utf-8")
    scored = ladder.score_run(tmp_path, correct=False)
    assert outcome_point(scored)["got"] == 0
    assert outcome_point(scored)["name"] == "outcome true"


def test_the_bench_takes_the_hidden_suites_verdicts(tmp_path, capsys):
    runs = tmp_path / "runs"
    for name in ("a", "b", "c"):
        (runs / name).mkdir(parents=True)
        (runs / name / "handoff.md").write_text(DONE, encoding="utf-8")
    hidden = tmp_path / "hidden.json"
    hidden.write_text('{"a": false, "b": true}', encoding="utf-8")
    assert bench.main(["--ladder", str(runs), "--hidden", str(hidden)]) == 0
    out = capsys.readouterr().out
    a, b, c = out.split("\n\n")[:3]
    assert "1 outcome true: no - done, while the hidden suite finds the tree" \
        " red" in a
    assert "1 outcome true: yes" in b
    assert "1 outcome consistent: yes" in c


def test_a_hidden_verdict_file_that_does_not_read_scores_nothing(tmp_path,
                                                                 capsys):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "handoff.md").write_text(DONE, encoding="utf-8")
    for text in ("not json", '{"a": "yes"}', "[true]"):
        hidden = tmp_path / "hidden.json"
        hidden.write_text(text, encoding="utf-8")
        assert bench.main(["--ladder", str(tmp_path / "a"), "--hidden",
                           str(hidden)]) == 1, text
        assert "--hidden" in capsys.readouterr().out
    assert bench.main(["--ladder", str(tmp_path / "a"), "--hidden",
                       str(tmp_path / "none.json")]) == 1


def test_a_stop_saying_it_asked_instead_of_doing_the_work_on_a_changed_tree():
    text = ESCALATED.replace("worker.md did the work, then asked for a ruling:",
                          "worker.md asked for a ruling instead of doing the"
                          " work:")
    assert got(ladder.score(text))["no_false"] == 0


def test_an_empty_or_unread_handoff_scores_nothing():
    scored = ladder.score("")
    assert scored["path"] == ladder.UNREAD
    assert scored["score"] == 0
    assert all(g == 0 for g in got(scored).values())


def test_the_summary_gives_each_path_its_mean_and_misses_per_point():
    rows = [ladder.score(DONE), ladder.score(DONE), ladder.score(ESCALATED)]
    total = ladder.summary(rows)
    assert total[ladder.DONE]["runs"] == 2
    assert total[ladder.DONE]["mean"] == 9
    assert total[ladder.DONE]["missed"]["why"] == 2
    assert total[ladder.PARKED]["mean"] == 6
    assert total[ladder.PARKED]["missed"]["decision"] == 1
    assert ladder.STOPPED not in total


def test_the_bench_scores_run_folders_on_the_ladder(tmp_path, capsys):
    for name, text in (("a", DONE), ("b", ESCALATED)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "handoff.md").write_text(text, encoding="utf-8")
    assert bench.main(["--ladder", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "done, 9/10" in out and "needs you: ruling, 6/10" in out
    assert "done: 1 run, mean 9" in out


def test_the_bench_refuses_a_ladder_with_no_handoff_to_score(tmp_path, capsys):
    assert bench.main(["--ladder", str(tmp_path)]) == 1
    assert "no handoff.md" in capsys.readouterr().out
