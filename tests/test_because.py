"""a step lists the reasons that shaped its work and what each led to, and a
reason the record cannot find is said so.

the step says it in its HANDOFF block, a BECAUSE item with its `from:` and
`led to:` lines under it. the runner holds every `led to:` to the record it
already has: a test id to the red proof and the gates' tests, a
`<file>:<lines>` to the diff, a TRIED, ASSUMED or QUESTION item to the
block's own, a DECIDED one to decisions.md. what it finds is printed in the
why section, what it does not is `(not in the record)` and counted as
`why_unbacked`.
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.bench import ladder
from agentweft.orchestrate import decisions
from agentweft.roles import resolver
from agentweft.runner import handoff, retro, summary

REASONS = ("BECAUSE:\n"
           "- TASK.md:3 says amounts round half up\n"
           "  from: TASK.md:3\n"
           "  led to: tests/test_calc.py::test_add_rounds\n"
           "- the old body truncated\n"
           "  from: calc.py:5\n"
           "  led to: calc.py:4-6\n"
           "- a decimal context would touch every caller\n"
           "  from: own read\n"
           "  led to: TRIED a global decimal context\n"
           "- ints stay ints\n"
           "  led to: ASSUMED amounts are ints only\n"
           "- the sign rule is the owner's to make\n"
           "  from: TASK.md:3\n"
           "  led to: QUESTION\n"
           "- the log format looked odd\n"
           "  from: log.py:2\n"
           "  led to: nothing\n")

BLOCK = ("HANDOFF\n"
         "DID:\n"
         "- calc.py: add rounds half up\n"
         + REASONS +
         "ASSUMED:\n"
         "- amounts are ints only\n"
         "  why: the task says integers\n"
         "  if wrong: floats round\n"
         "TRIED:\n"
         "- a global decimal context - it changes every caller\n"
         "QUESTION: do negatives round away from zero? TASK.md:3\n"
         "RECOMMEND: away from zero\n"
         "SIZE: one line\n"
         "END HANDOFF\n")

NO_REASONS = BLOCK.replace(REASONS, "")

GIT = {"git": True, "start": None, "commits": [], "status": [], "log": [],
       "files": [("calc.py", 3, 1, "uncommitted"),
                 ("tests/test_calc.py", 6, 0, "untracked")],
       "ranges": {("calc.py", "uncommitted"): "4-6",
                  ("tests/test_calc.py", "untracked"): "1-6"}}

PROOF = {"how": "gate", "step": "worker.md", "gate": "red-test",
         "source": "written", "tests": {"tests/test_calc.py": "0" * 64},
         "ids": ["tests/test_calc.py::test_add_rounds"]}


def built(block, writes="product", decided=(), proof=PROOF, changes=GIT):
    return summary.build("r1", "flow", "t", [summary.a_pass(
        "worker.md", "worker", 1.0, block, [], False, "ok", "",
        writes=writes)], changes, list(decided), "", proof=proof)


def section(lines, heading):
    at = lines.index(heading)
    out = []
    for line in lines[at + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def why_of(lines):
    view = lines[:lines.index("## full record")]
    return view[view.index("## why"):view.index("## not done")]


def test_a_because_item_keeps_its_from_and_led_to_lines():
    got = handoff.parse("done\n\n" + BLOCK)
    assert got["because"][0] == ("TASK.md:3 says amounts round half up\n"
                                 "from: TASK.md:3\n"
                                 "led to: tests/test_calc.py::test_add_rounds")
    assert handoff.reason(got["because"][3]) == {
        "reason": "ints stay ints", "from": "",
        "led_to": "ASSUMED amounts are ints only"}
    assert handoff.reason("a | from: a.py:1 | led to: nothing") == {
        "reason": "a", "from": "a.py:1", "led_to": "nothing"}
    assert got["other"] == {}


def test_each_reason_is_in_the_why_section_with_what_it_led_to():
    lines = built(handoff.parse(BLOCK))
    why = why_of(lines)
    assert "worker's reasons, and what each led to:" in why
    for said in (
            "- because TASK.md:3 says amounts round half up (TASK.md:3) ->"
            " tests/test_calc.py::test_add_rounds",
            "- because the old body truncated (calc.py:5) -> calc.py:4-6",
            "- because a decimal context would touch every caller (own read)"
            " -> TRIED a global decimal context",
            "- because ints stay ints (own read) -> ASSUMED amounts are ints"
            " only"):
        assert said in why, said
    full = section(lines, "## reasons")
    assert ("- worker: because the sign rule is the owner's to make"
            " (TASK.md:3) -> QUESTION") in full
    assert ("- worker: because the log format looked odd (log.py:2) ->"
            " nothing") in full
    assert "- why_unbacked: 0" in full
    assert not [l for l in lines if "not in the record" in l]


def test_the_reasons_sit_between_what_was_done_and_what_was_dropped():
    why = why_of(built(handoff.parse(BLOCK)))
    assert why.index("worker did:") < why.index(
        "worker's reasons, and what each led to:") < why.index(
        "tried and dropped, and why:") < why.index(
        "assumed - tell me if wrong:")


def test_a_reason_that_names_nothing_in_the_record_says_so_and_is_counted():
    block = handoff.parse(BLOCK.replace(
        "led to: tests/test_calc.py::test_add_rounds",
        "led to: tests/test_calc.py::test_never_written").replace(
        "led to: calc.py:4-6", "led to: calc.py:40-41").replace(
        "led to: TRIED a global decimal context", "led to: TRIED a cache"))
    lines = built(block)
    full = section(lines, "## reasons")
    assert ("- worker: because TASK.md:3 says amounts round half up"
            " (TASK.md:3) -> (not in the record)") in full
    assert ("- worker: because the old body truncated (calc.py:5) -> (not in"
            " the record)") in full
    assert "- why_unbacked: 3" in full
    assert ("- reasons the record does not show: worker: TASK.md:3 says"
            " amounts round half up (led to: tests/test_calc.py::"
            "test_never_written)") in section(lines, "## not verified")


def led_to(said):
    block = handoff.parse(BLOCK.replace("led to: nothing", "led to: " + said))
    full = section(built(block), "## reasons")
    line = [l for l in full if "the log format looked odd" in l][0]
    return line.split(" -> ", 1)[1], full


def test_a_bare_tried_assumed_or_decided_is_not_in_the_record():
    ruled = decisions.Decision("keep the spec order", "the spec lists it",
                               datetime.datetime(2026, 1, 5, 21, 40))
    for bare in ("TRIED", "ASSUMED", "DECIDED"):
        block = handoff.parse(BLOCK.replace("led to: nothing",
                                            "led to: " + bare))
        full = section(built(block, decided=[ruled]), "## reasons")
        assert ("- worker: because the log format looked odd (log.py:2) ->"
                " (not in the record)") in full, bare
        assert "- why_unbacked: 1" in full, bare


def test_a_tried_text_too_short_to_name_an_item_is_not_in_the_record():
    got, full = led_to("TRIED a")
    assert got == "(not in the record)"
    assert "- why_unbacked: 1" in full


def test_a_bare_question_stands_when_the_block_asks_one():
    got, full = led_to("QUESTION")
    assert got == "QUESTION"
    assert "- why_unbacked: 0" in full
    block = handoff.parse(BLOCK.replace("led to: nothing", "led to: QUESTION")
                          .replace("QUESTION: do negatives round away from"
                                   " zero? TASK.md:3\n", ""))
    assert "- why_unbacked: 2" in section(built(block), "## reasons")


def test_a_decided_reason_is_held_to_decisions_md():
    block = handoff.parse(BLOCK.replace("led to: nothing",
                                        "led to: DECIDED keep the spec order"))
    ruled = decisions.Decision("keep the spec order", "the spec lists it",
                               datetime.datetime(2026, 1, 5, 21, 40))
    full = section(built(block, decided=[ruled]), "## reasons")
    assert ("- worker: because the log format looked odd (log.py:2) ->"
            " DECIDED keep the spec order") in full
    full = section(built(block), "## reasons")
    assert ("- worker: because the log format looked odd (log.py:2) -> (not in"
            " the record)") in full


def test_a_block_with_no_because_key_reads_none_given_never_missing():
    block = handoff.parse(NO_REASONS)
    assert block["state"] == handoff.PRESENT
    assert block["because"] == []
    lines = built(block)
    why = why_of(lines)
    at = why.index("worker's reasons, and what each led to:")
    assert why[at + 1] == "- none given"
    assert "- worker: none given" in section(lines, "## reasons")
    assert not [l for l in section(lines, "## reasons") if "missing" in l]
    assert "- handoff missing: worker.md" not in lines


def test_a_block_recorded_before_the_key_existed_still_builds():
    old = handoff.parse(NO_REASONS)
    del old["because"]
    lines = built(old)
    assert "- worker: none given" in section(lines, "## reasons")


def test_a_step_that_writes_nothing_and_gave_no_reason_is_not_listed():
    lines = built(handoff.parse(NO_REASONS), writes="none")
    assert "## reasons" not in lines
    assert not [l for l in lines if "none given" in l]


def test_the_runner_reads_what_each_step_of_a_flow_writes():
    from agentweft import runner

    fm = runner.config("build-feature")
    assert summary.writes_of(fm, "tester.md") == "tests"
    assert summary.writes_of(fm, "worker.md") == "product"
    assert summary.writes_of(fm, "planner.md") == "none"
    assert summary.writes_of(fm, "nobody.md") == ""


def why_point(text):
    scored = ladder.score(text)
    return [p for p in scored["points"] if p["point"] == "why"][0]


def test_the_ladder_keeps_the_why_point_when_every_reason_resolves():
    point = why_point("\n".join(built(handoff.parse(BLOCK))))
    assert point["got"] == 1
    assert "6 reasons resolved" in point["line"]


def test_the_ladder_takes_the_why_point_for_a_reason_not_in_the_record():
    block = handoff.parse(BLOCK.replace(
        "led to: calc.py:4-6", "led to: calc.py:40-41"))
    point = why_point("\n".join(built(block)))
    assert point["got"] == 0
    assert "1 reason not in the record" in point["line"]


def test_the_ladder_takes_the_why_point_from_a_writing_step_with_no_reason():
    point = why_point("\n".join(built(handoff.parse(NO_REASONS))))
    assert point["got"] == 0
    assert "worker gave no reason the record holds" in point["line"]


def test_the_reasons_rule_does_not_apply_to_a_conflict_stop():
    text = "\n".join(built(handoff.parse(NO_REASONS)))
    text = text.replace("## run\n", "## run\n- cause: conflict at worker.md\n")
    point = why_point(text)
    assert "not applicable" in point["line"]


def test_the_ladder_counts_why_unbacked_per_run():
    block = handoff.parse(BLOCK.replace(
        "led to: calc.py:4-6", "led to: calc.py:40-41"))
    assert ladder.score("\n".join(built(block)))["why_unbacked"] == 1
    assert ladder.score("\n".join(built(handoff.parse(BLOCK))))[
        "why_unbacked"] == 0


def test_the_retro_is_handed_the_reasons_first(tmp_path):
    line = {"seq": 2, "step": "worker.md", "outcome": "ok",
            "handoff": handoff.parse(BLOCK)}
    said = retro.reasons([(line, Path(tmp_path))])
    assert said[0] == ("- seq 2 worker.md because TASK.md:3 says amounts round"
                       " half up (from TASK.md:3) -> led to"
                       " tests/test_calc.py::test_add_rounds")
    text = retro.prompt("r1", "flow", "done", Path(tmp_path),
                        ["- seq 1 worker.md, failed: red"], reasons=said)
    assert text.index(said[0]) < text.index("why each failed attempt failed")


def test_every_role_is_asked_for_its_reasons_and_what_each_led_to():
    shared = resolver.shared_rules()
    assert "    BECAUSE:\n" in shared
    assert shared.index("    DID:") < shared.index("    BECAUSE:") \
        < shared.index("    VERIFIED:")
    assert "      from: " in shared and "      led to: " in shared
    assert "never a trail of thought" in shared
