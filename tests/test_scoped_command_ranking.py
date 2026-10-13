"""the short suite is only for a change the ranking vouches for.

a ranking that is missing, empty or in a shape the parser skips is no evidence
the change is small, so the long command runs. the cold/hot split itself is
pinned in test_scoped_command.py.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates

RANKING = "src/core.py 0.92\nsrc/util.py 0.15\n"


def says(word):
    return [sys.executable, "-c",
            "import sys; sys.stderr.write('" + word + "'); sys.exit(1)"]


def ran(ranking, text, threshold=None):
    cold = {"command": says("short")}
    if threshold is not None:
        cold["threshold"] = threshold
    g = gates.build({"gate": "command", "command": says("long"),
                     "cold": cold}, ranking=ranking)
    return g.run(text).detail


def test_no_ranking_runs_the_long_command_even_for_a_file_that_would_be_cold():
    assert "long" in ran("", "i changed src/util.py")
    assert "no risk map" in ran("", "i changed src/util.py")


def test_a_ranking_of_none_runs_the_long_command():
    assert "long" in ran(None, "i changed src/util.py")


def test_a_blank_ranking_runs_the_long_command():
    assert "long" in ran("\n   \n", "i changed src/util.py")


def test_a_ranking_the_parser_skips_runs_the_long_command():
    prose = "the map is not ready yet\nsee the dashboard\n"
    assert "long" in ran(prose, "i changed src/util.py")


def test_the_same_ranking_scopes_once_it_is_present():
    assert "short" in ran(RANKING, "i changed src/util.py")
    assert "long" in ran("", "i changed src/util.py")


def test_a_score_exactly_at_the_threshold_is_hot():
    assert "long" in ran("src/util.py 0.5\n", "i changed src/util.py",
                         threshold=0.5)


def test_a_ranking_that_puts_a_colon_after_the_path_still_marks_it_hot():
    assert "long" in ran("src/core.py: 0.92\n", "i changed src/core.py")


def test_a_file_the_ranking_does_not_know_is_cold():
    assert "short" in ran(RANKING, "i changed src/other.py")


def test_a_hot_file_is_found_however_the_step_spells_its_path():
    for spelling in ("./src/core.py", "app/src/core.py", "src\\core.py"):
        assert "long" in ran(RANKING, "i changed " + spelling), spelling
