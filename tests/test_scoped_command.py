"""a command gate runs the short suite when nothing the step touches is hot.

the long suite is what runs unless the ranking says otherwise, so a step that
touches a file everything depends on gets everything run against it.
"""
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.guardrails import gates
from agentweft.roles import resolver

RANKING = "src/core.py 0.92\nsrc/util.py 0.15\n"


def says(word):
    """fails on purpose, so the word lands in the detail and shows which ran."""
    return [sys.executable, "-c",
            "import sys; sys.stderr.write('" + word + "'); sys.exit(1)"]


def scoped(ranking, threshold=None):
    cold = {"command": says("short")}
    if threshold is not None:
        cold["threshold"] = threshold
    return gates.build({"gate": "command", "command": says("long"),
                        "cold": cold}, ranking=ranking)


def test_a_change_to_a_cold_file_runs_the_short_command():
    r = scoped(RANKING).run("i changed src/util.py")
    assert "short" in r.detail


def test_a_change_to_a_hot_file_runs_the_long_command():
    r = scoped(RANKING).run("i changed src/util.py and src/core.py")
    assert "long" in r.detail
    assert "src/core.py" in r.detail


def test_the_short_command_passes_on_its_own_exit_code():
    g = gates.build({"gate": "command", "command": says("long"),
                     "cold": {"command": [sys.executable, "-c", "pass"]}},
                    ranking=RANKING)
    assert g.run("i changed src/util.py")


def test_the_threshold_is_the_gates_own():
    r = scoped(RANKING, threshold=0.1).run("i changed src/util.py")
    assert "long" in r.detail


def test_a_step_that_names_no_file_runs_the_long_command():
    r = scoped(RANKING).run("all done, nothing to report")
    assert "long" in r.detail


def test_a_cold_block_with_no_command_fails():
    g = gates.build({"gate": "command", "command": says("long"),
                     "cold": {"threshold": 0.5}}, ranking=RANKING)
    r = g.run("i changed src/util.py")
    assert not r
    assert "cold" in r.detail


def test_the_ranking_a_run_holds_reaches_its_gates():
    fm = runner.config("fix-with-test")
    by_role = resolver.resolve(fm.raw, runner.flow_path("fix-with-test"))
    run = runner.Run("fix-with-test", fm, by_role)
    run.ranking = RANKING
    assert all(g.ranking == RANKING for g in run.gates_for("verify.md"))
