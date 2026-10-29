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
import subprocess
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
    assert "5 reasons resolved, 1 led to nothing" in point["line"]


def test_the_ladder_takes_the_why_point_when_every_reason_led_to_nothing():
    nothing = ("BECAUSE:\n"
               "- the log format looked odd\n"
               "  from: log.py:2\n"
               "  led to: nothing\n"
               "- the names looked long\n"
               "  led to: none\n")
    point = why_point("\n".join(built(handoff.parse(BLOCK.replace(
        REASONS, nothing)))))
    assert point["got"] == 0
    assert "worker gave no reason that led to anything" in point["line"]


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


# the words of each reason in BLOCK, which the retro is never handed
SAID = ("TASK.md:3 says amounts round half up", "the old body truncated",
        "a decimal context would touch every caller", "ints stay ints",
        "the sign rule is the owner's to make", "the log format looked odd")


def a_run(changes=GIT, proof=PROOF):
    import types

    return types.SimpleNamespace(fm=None, decided=lambda: [],
                                 tree=types.SimpleNamespace(
                                     changes=lambda: changes),
                                 order=types.SimpleNamespace(proof=proof))


def a_trail(folder, *lines):
    import types

    return types.SimpleNamespace(folder=folder, closed=[
        (types.SimpleNamespace(written=line), "ok") for line in lines])


def test_the_retro_is_handed_where_each_reason_led_never_its_words(tmp_path):
    line = {"seq": 2, "step": "worker.md", "outcome": "ok",
            "handoff": handoff.parse(BLOCK)}
    said = retro.evidence(a_run(), a_trail(tmp_path, line), None,
                          [(line, tmp_path)])
    assert said == [
        "- seq 2 worker.md -> test tests/test_calc.py::test_add_rounds",
        "- seq 2 worker.md -> the diff of calc.py, lines 4-6",
        "- seq 2 worker.md -> TRIED item 1 of its handoff",
        "- seq 2 worker.md -> ASSUMED item 1 of its handoff",
        "- seq 2 worker.md -> a QUESTION of its handoff"]
    (tmp_path / summary.FILE).write_text("\n".join(built(handoff.parse(
        BLOCK))) + "\n", encoding="utf-8")
    text = retro.prompt("r1", "flow", "done", tmp_path, [], more=retro.parts(
        [(line, tmp_path)], ["- none"], [], [], [], 3, led=said))
    for line in said:
        assert line in text
    for words in SAID:
        assert words not in text, words
    assert "reasons" not in text.split("handoff.md:")[1]
    kept = (tmp_path / summary.FILE).read_text(encoding="utf-8")
    assert "## reasons" in kept and SAID[0] in kept


def test_a_run_s_retro_prompt_holds_none_of_the_steps_reason_words(
        tmp_path, monkeypatch, fake_cli):
    from agentweft.runner import engine
    from test_stops import CLAUDE, a_flow, answer, the_folder

    a_flow(tmp_path, monkeypatch, "says-why", ["worker"],
           tail="retro: true\n" + CLAUDE)
    cli_ = fake_cli(answer("done\n\n" + BLOCK),
                    answer("## change first\n- none\n"))
    assert engine.main() == 0
    text = cli_.calls[-1]["stdin"].decode("utf-8")
    assert "- seq 1 worker.md -> TRIED item 1 of its handoff" in text
    for words in SAID:
        assert words not in text, words
    kept = (the_folder() / summary.FILE).read_text(encoding="utf-8")
    for words in SAID:
        assert words in kept, words


def test_a_reason_the_record_does_not_hold_is_not_handed_as_evidence(
        tmp_path):
    line = {"seq": 2, "step": "worker.md", "outcome": "ok",
            "handoff": handoff.parse(BLOCK)}
    said = retro.evidence(a_run(changes={}, proof=None),
                          a_trail(tmp_path, line), None, [(line, tmp_path)])
    assert said == ["- seq 2 worker.md -> TRIED item 1 of its handoff",
                    "- seq 2 worker.md -> ASSUMED item 1 of its handoff",
                    "- seq 2 worker.md -> a QUESTION of its handoff"]


def test_a_decided_reason_is_handed_as_the_ruling_it_is_held_to(tmp_path):
    ruled = decisions.Decision("keep the spec order", "the spec lists it",
                               datetime.datetime(2026, 1, 5, 21, 40))
    line = {"seq": 3, "step": "worker.md", "outcome": "ok",
            "handoff": handoff.parse(BLOCK.replace(
                "led to: nothing", "led to: DECIDED keep the spec order"))}
    run = a_run()
    run.decided = lambda: [ruled]
    said = retro.evidence(run, a_trail(tmp_path, line), None,
                          [(line, tmp_path)])
    assert said[-1] == ("- seq 3 worker.md -> decisions.md "
                        + summary.stamp(ruled))


def test_a_handoff_with_no_reasons_reaches_the_retro_as_it_is():
    text = "\n".join(built(handoff.parse(NO_REASONS), writes="none")) + "\n"
    assert REASONS_LABEL not in text and "## reasons" not in text
    assert summary.without_reasons(text) == text


def test_a_handoff_reaches_the_retro_less_its_reasons_lines_only():
    block = handoff.parse(BLOCK.replace("led to: calc.py:4-6",
                                        "led to: calc.py:40-41"))
    lines = built(block)
    at = lines.index("## reasons")
    end = next(n for n in range(at + 1, len(lines))
               if lines[n].startswith("## "))
    label = lines.index(REASONS_LABEL)
    items = next(n for n in range(label + 1, len(lines))
                 if not lines[n].startswith("- "))
    assert any(l.startswith(summary.UNSHOWN) for l in lines)
    assert summary.without_reasons("\n".join(lines)).split("\n") == [
        l for n, l in enumerate(lines)
        if not (at <= n < end or label <= n < items
                or l.startswith(summary.UNSHOWN))]


REASONS_LABEL = "worker's reasons, and what each led to:"


def test_no_retro_prompt_names_the_steps_reasons_any_more():
    role = resolver.role_prompt("retro.md")
    skill = resolver.skill("retro")
    assert "the reasons each step" not in role
    assert "reasons the steps gave" not in skill
    assert "evidence in the record" in skill


def held_as(said, block=BLOCK, decided=(), proof=PROOF, changes=GIT,
            output=""):
    """-> what the reasons section prints for the log-format reason led to
    `said`, the block handed over in `output` when there is one."""
    text = block.replace("led to: nothing", "led to: " + said)
    lines = summary.build("r1", "flow", "t", [summary.a_pass(
        "worker.md", "worker", 1.0, handoff.parse(text), [], False, "ok",
        output.replace("{block}", text), writes="product")], changes,
        list(decided), "", proof=proof)
    full = section(lines, "## reasons")
    return [l for l in full if "the log format looked odd" in l][0].split(
        " -> ", 1)[1]


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def test_a_changed_file_and_a_function_its_diff_touches_are_in_the_record(
        tmp_path):
    place = tmp_path / "repo"
    place.mkdir()
    git(place, "init", "-q")
    git(place, "config", "user.email", "t@t")
    git(place, "config", "user.name", "t")
    (place / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n"
        "    return a * b\n", encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "start")
    start = summary.tree(place)
    (place / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n"
        "    return a * b\n", encoding="utf-8")
    (place / "rounding.py").write_text("def half_up(x):\n    return x\n",
                                       encoding="utf-8")
    changes = start.changes()
    for said in ("calc.py `add`",
                 "calc.py `add`, placed before the sign check (see ASSUMED)",
                 "calc.py `add` (only the adder changes)",
                 "rounding.py `half_up`"):
        assert held_as(said, changes=changes) == said, said
    for said in ("calc.py `mul`", "calc.py `subtract`",
                 "parse.py `add`"):
        assert held_as(said, changes=changes) == summary.UNHELD, said


def test_changed_lines_with_a_note_after_them_are_in_the_record():
    for said in ("calc.py:4-6 (additions only)",
                 "calc.py new lines 4-6, indented as a continuation of the"
                 " bullet",
                 "calc.py lines 5"):
        assert held_as(said) == said, said
    for said in ("calc.py:40-41 (additions only)",
                 "calc.py new lines 40-41, indented as before"):
        assert held_as(said) == summary.UNHELD, said


def test_a_list_of_test_ids_is_in_the_record_when_each_one_is():
    proof = dict(PROOF, ids=PROOF["ids"] + ["tests/test_calc.py::test_half"])
    said = "tests/test_calc.py::test_add_rounds, tests/test_calc.py::test_half"
    assert held_as(said, proof=proof) == said
    gone = "tests/test_calc.py::test_add_rounds, tests/test_calc.py::test_gone"
    assert held_as(gone, proof=proof) == summary.UNHELD


def test_nothing_with_a_note_after_it_led_to_nothing():
    said = "nothing; output code untouched (calc.py:4)"
    assert held_as(said) == said


def test_a_test_in_a_file_the_red_proof_holds_without_ids_is_in_the_record():
    supplied = {"how": "gate", "step": "worker.md", "gate": "red-test",
                "source": "supplied", "ids": [],
                "tests": {"tests/test_bug_report.py": "0" * 64}}
    said = "tests/test_bug_report.py::test_halves_round_up"
    assert held_as(said, proof=supplied) == said
    assert held_as("tests/test_other.py::test_halves_round_up",
                   proof=supplied) == summary.UNHELD


OWN = ("DECIDED: Leave the order between option errors unspecified. Keep"
       " the code's current order.\nwhy: TASK.md:3 does not order them\n\n"
       "{block}")


def test_a_decided_reason_is_held_to_the_steps_own_decided_line():
    for said in ("DECIDED leave the order within option values unspecified",
                 "DECIDED add no spec line or test for it"):
        assert held_as(said, output=OWN) == said, said
        assert held_as(said) == summary.UNHELD, said
    assert held_as("DECIDED", output=OWN) == summary.UNHELD
    assert held_as("DECIDED a", output=OWN) == summary.UNHELD


def test_a_decided_reason_is_held_to_a_ruling_by_the_names_it_quotes():
    ruled = decisions.Decision(
        "worker.md decided for tester.md: keep the code's current order"
        " (`--places`, then `--mode`)", "the spec leaves it open",
        datetime.datetime(2026, 1, 5, 21, 40))
    said = "DECIDED keep `--places`, `--mode` order; no test pins it"
    assert held_as(said, decided=[ruled]) == said
    assert held_as(said) == summary.UNHELD
    assert held_as("DECIDED keep `--places`, `--strict` order",
                   decided=[ruled]) == summary.UNHELD


def test_the_steps_own_would_pass_and_catch_lines_are_in_the_record():
    output = ("WOULD PASS: an add that rounds only positive amounts\n"
              "CATCH: add(-1, -2) must be -3\n\n{block}")
    for said in ("the WOULD PASS / CATCH lines",
                 "the WOULD PASS/CATCH lines (negative amounts)"):
        assert held_as(said, output=output) == said, said
        assert held_as(said) == summary.UNHELD, said


def test_a_reason_that_names_nothing_on_record_stays_out_of_it():
    ruled = decisions.Decision("keep the spec order", "the spec lists it",
                               datetime.datetime(2026, 1, 5, 21, 40))
    for said in ("DECIDED the plan has no CONFLICT",
                 "DECIDED no test for those two",
                 "ASSUMED ints only, never floats",
                 "TRIED a decimal context run in a temp dir",
                 "the review lines", "DOUBTS"):
        assert held_as(said, decided=[ruled], output=OWN.replace(
            "DECIDED: Leave", "Leave")) == summary.UNHELD, said


CHOSEN = {"assumed": [
    "the month is checked before the store is loaded\n"
    "why: TASK.md:4\nif wrong: the error order flips",
    '"exactly one character" means one Unicode code point\n'
    "why: TASK.md:11 says one character\nif wrong: a surrogate pair is two"],
    "tried": ["running `top` on a gzip file with `--output` in a temp dir"
              " - it wrote outside the place"]}
NOTHING_HELD = summary.record_of([], {}, [], None)


def test_a_reason_names_its_assumed_or_tried_item_by_its_own_first_words():
    shared = " ".join(resolver.shared_rules().split())
    assert "TRIED <the item>" not in shared and "ASSUMED <the item>" not in shared
    assert ("TRIED <its first words, copied>, ASSUMED <its first words,"
            " copied>") in shared
    assert ("a TRIED or ASSUMED one by its own first words, three or more,"
            " copied from it, never a label of your own for it") in shared


def test_an_item_named_by_its_own_first_words_is_held_and_a_label_is_not():
    held = summary.held_at
    assert held('ASSUMED "exactly one character" means one Unicode code point',
                CHOSEN, NOTHING_HELD) == "ASSUMED item 2 of its handoff"
    assert held("TRIED running `top` on a gzip file", CHOSEN,
                NOTHING_HELD) == "TRIED item 1 of its handoff"
    for label in ("ASSUMED len(C) == 1", "ASSUMED month error before store"
                  " error", "TRIED gzip and --output run in a temp dir"):
        assert held(label, CHOSEN, NOTHING_HELD) == "", label


def test_decided_is_asked_for_only_for_a_ruling_and_a_choice_is_assumed():
    shared = " ".join(resolver.shared_rules().split())
    assert "DECIDED <the ruling>" not in shared
    assert ("DECIDED <a ruling you were handed, or your own `DECIDED:` line>"
            in shared)
    assert ("DECIDED only for a ruling you were handed or your own `DECIDED:`"
            " line: a choice of your own is an ASSUMED item, and a reason that"
            " led you to leave a thing alone or out led to `nothing`") in shared


def test_a_decided_reason_with_no_ruling_and_no_decided_line_is_held_nowhere():
    ruled = decisions.Decision("keep the spec order", "the spec lists it",
                               datetime.datetime(2026, 1, 5, 21, 40))
    for said in ("DECIDED no test for those two",
                 "DECIDED the plan has no CONFLICT",
                 "DECIDED TASK.md gets new lines under line 43 only"):
        assert summary.held_at(said, CHOSEN, NOTHING_HELD) == "", said
        assert summary.held_at(said, CHOSEN, dict(
            NOTHING_HELD, decided=[ruled])) == "", said
    assert summary.held_at("DECIDED keep the spec order", CHOSEN, dict(
        NOTHING_HELD, decided=[ruled])) == "decisions.md " + summary.stamp(ruled)


def test_every_role_is_asked_for_its_reasons_and_what_each_led_to():
    shared = resolver.shared_rules()
    assert "    BECAUSE:\n" in shared
    assert shared.index("    DID:") < shared.index("    BECAUSE:") \
        < shared.index("    VERIFIED:")
    assert "      from: " in shared and "      led to: " in shared
    assert "never a trail of thought" in shared
