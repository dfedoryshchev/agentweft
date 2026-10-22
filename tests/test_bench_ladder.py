"""a handoff is scored on a ten-point ladder, one named line per point, by a
program. the strict 0-3 score is 3 on every run now, so it tells nothing
apart; the ladder tells a 6 from a 9, per path.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.bench import __main__ as bench
from agentweft.bench import ladder

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


def test_a_decided_question_shown_open_on_a_done_run_is_a_false_line():
    text = DONE.replace(
        "- none: nothing waits on you.",
        "- which option comes first\n  raised by planner; cites TASK.md:23"
        "\n  recommendation: the order the spec lists").replace(
        "- none on record in decisions.md",
        "- on record: 2026-01-05 21:40  options keep the spec's order")
    marks = got(ladder.score(text))
    assert marks["decision"] == 0
    assert marks["no_false"] == 0


def test_an_unbacked_verified_line_loses_checks_backed():
    text = DONE.replace("saw: 38 passed in 5.26s -> backed",
                        "saw: 38 passed -> unbacked: no such command in the"
                        " step's transcript")
    assert got(ladder.score(text))["checks"] == 0


def test_a_done_word_on_a_tree_the_hidden_suite_finds_red_is_not_true():
    assert got(ladder.score(DONE, correct=False))["outcome"] == 0
    assert got(ladder.score(DONE, correct=True))["outcome"] == 1


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
