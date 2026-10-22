"""a defect a step finds beside the change, one the task did not name, is
listed in the handoff with whether it was fixed and by which test.

the step says it in its HANDOFF block, an ADJACENT item with its `fixed:`
and `test:` lines under it; the run's handoff.md lists each once, the next
step and the retro are handed it, and a fix whose test file the run never
touched says so.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.runner import handoff, retro, summary
from agentweft.runner.handoff import Handoff

BLOCK = ("HANDOFF\n"
         "DID:\n"
         "- cli.py: count reads every file named\n"
         "DOUBTS:\n"
         "- none\n"
         "ADJACENT:\n"
         "- reader.py:14 crashes on an empty file with IndexError\n"
         "  fixed: yes\n"
         "  test: tests/test_reader.py::test_empty_file\n"
         "- stats.py:30 rounds p50 of five values down\n"
         "  fixed: no\n"
         "  test: none\n"
         "READ:\n"
         "- cli.py:1-40 - the commands\n"
         "END HANDOFF\n")

GIT = {"git": True, "commits": [],
       "files": [("cli.py", 4, 1, "uncommitted"),
                 ("reader.py", 2, 1, "uncommitted"),
                 ("tests/test_reader.py", 6, 0, "untracked")]}


def built(block, changes=None, role="worker"):
    return summary.build("r1", "flow", "t", [summary.a_pass(
        role + ".md", role, 1.0, block, [], False, "ok", "")],
        changes or {"git": False}, [], "")


def test_an_adjacent_item_keeps_its_fixed_and_test_lines():
    got = handoff.parse("done\n\n" + BLOCK)
    assert got["adjacent"] == [
        "reader.py:14 crashes on an empty file with IndexError\nfixed: yes\n"
        "test: tests/test_reader.py::test_empty_file",
        "stats.py:30 rounds p50 of five values down\nfixed: no\ntest: none"]
    assert got["other"] == {}


def test_the_older_piped_form_is_still_read():
    said = summary.beside("reader.py:14 crashes | fixed: yes"
                          " | test: tests/test_reader.py::test_empty_file")
    assert said == {"defect": "reader.py:14 crashes", "fixed": True,
                    "test": "tests/test_reader.py::test_empty_file"}


def test_each_found_defect_is_listed_with_whether_it_was_fixed_and_its_test():
    lines = built(handoff.parse(BLOCK), GIT)
    at = lines.index("## found beside the change")
    assert lines[at + 1:at + 3] == [
        "- worker: reader.py:14 crashes on an empty file with IndexError -"
        " fixed, shown by tests/test_reader.py::test_empty_file",
        "- worker: stats.py:30 rounds p50 of five values down - not fixed"]


def test_the_default_view_says_what_was_fixed_beside_it_and_what_was_left():
    lines = built(handoff.parse(BLOCK), GIT)
    view = lines[:lines.index("## full record")]
    why = view[view.index("## why"):view.index("## not done")]
    left = view[view.index("## not done"):view.index("## product gaps")]
    assert "also fixed beside the change:" in why
    assert ("- reader.py:14 crashes on an empty file with IndexError, shown by"
            " tests/test_reader.py::test_empty_file (worker)") in why
    assert "found beside the change, not fixed:" in left
    assert "- stats.py:30 rounds p50 of five values down (worker)" in left


def test_a_fix_that_names_no_test_or_a_test_the_run_never_touched_says_so():
    block = handoff.parse(BLOCK.replace(
        "  test: tests/test_reader.py::test_empty_file\n", "  test: none\n")
        .replace("  fixed: no\n  test: none\n",
                 "  fixed: yes\n  test: tests/test_stats.py::test_p50\n"))
    lines = built(block, GIT)
    assert ("- worker: reader.py:14 crashes on an empty file with IndexError -"
            " fixed, no test names it") in lines
    assert ("- worker: stats.py:30 rounds p50 of five values down - fixed,"
            " shown by tests/test_stats.py::test_p50; its file did not change"
            " in this run") in lines


def test_a_defect_two_steps_found_is_listed_once_as_the_last_one_left_it():
    worker = handoff.parse(BLOCK)
    patcher = handoff.parse(
        "HANDOFF\nDID:\n- stats.py: p50 rounds up\nADJACENT:\n"
        "- stats.py:30 rounds p50 of five values down\n  fixed: yes\n"
        "  test: tests/test_reader.py::test_empty_file\nEND HANDOFF\n")
    lines = summary.build("r1", "flow", "t", [
        summary.a_pass("worker.md", "worker", 1.0, worker, [], False, "ok",
                       ""),
        summary.a_pass("patcher.md", "patcher", 1.0, patcher, [], False,
                       "ok", "")], GIT, [], "")
    at = lines.index("## found beside the change")
    found = [l for l in lines[at + 1:] if l.startswith("- ")][:2]
    assert found[1] == ("- worker, patcher: stats.py:30 rounds p50 of five"
                        " values down - fixed, shown by"
                        " tests/test_reader.py::test_empty_file")


def test_a_run_whose_steps_found_nothing_beside_it_has_no_such_section():
    lines = built(handoff.parse(BLOCK.split("ADJACENT:")[0]
                                + "READ:\n- none\nEND HANDOFF\n"))
    assert "## found beside the change" not in lines
    assert not [l for l in lines if "beside the change" in l]


def test_the_next_step_is_handed_what_was_found_beside_the_change():
    said = "\n".join(handoff.brief(Handoff("worker", "x\n" + BLOCK)))
    assert "worker found beside the change:" in said
    assert ("- stats.py:30 rounds p50 of five values down\n  fixed: no\n"
            "  test: none") in said


def test_the_retro_is_handed_each_defect_found_beside_the_change(tmp_path):
    line = {"seq": 2, "step": "worker.md", "outcome": "ok",
            "handoff": handoff.parse(BLOCK)}
    got = retro.handed([(line, Path(tmp_path))])
    assert ("- seq 2 worker.md found beside the change: stats.py:30 rounds"
            " p50 of five values down - not fixed") in got
    assert ("- seq 2 worker.md found beside the change: reader.py:14 crashes"
            " on an empty file with IndexError - fixed, shown by"
            " tests/test_reader.py::test_empty_file") in got


def test_every_step_is_asked_for_what_it_found_beside_the_change():
    from agentweft.roles import resolver

    text = resolver.fragment("handoff")
    assert "ADJACENT:" in text
    assert "fixed: <yes or no>" in text and "test: <" in text
    assert "|" not in text.split("END HANDOFF")[0]


def test_the_retro_keeps_a_defect_left_not_fixed_as_a_defect_fact():
    from agentweft.roles import resolver

    skill = resolver.skill("retro")
    assert "found beside the change" in skill
    assert "`defect` fact" in skill
