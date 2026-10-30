"""every step hands over what it did, what it checked and what it doubts.

the block at the end of a step's answer is parsed onto its steps.jsonl line,
handed to the next step first, and folded into the run's handoff.md, which is
written on every end: finished, parked, gate failed, budget, crash.
"""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.orchestrate import decisions, park
from agentweft.roles import resolver
from agentweft.runner import engine, handoff, prompts, stops, summary
from agentweft.runner.handoff import Handoff

BLOCK = ("HANDOFF\n"
         "DID:\n"
         "- calc.py: add returns a + b\n"
         "VERIFIED:\n"
         "- 1 passed | cmd: python -m pytest -q test_calc.py | saw: 1 passed\n"
         "NOT VERIFIED:\n"
         "- the cli path - no cli in this repo\n"
         "ASSUMED:\n"
         "- ints only | why: the task says integers | if wrong: floats round\n"
         "DOUBTS:\n"
         "- sub still returns a + b\n"
         "MUST NOT MISS:\n"
         "- TASK.md:3 - amounts are exact decimals, never floats\n"
         "TRIED:\n"
         "- none\n"
         "READ:\n"
         "- calc.py:1-4 - the whole module\n"
         "END HANDOFF\n")


# --- the block grammar ---------------------------------------------------


def test_a_block_at_the_end_of_an_answer_is_parsed_into_its_sections():
    got = handoff.parse("fixed it\n\n" + BLOCK)
    assert got["state"] == "present"
    assert got["did"] == ["calc.py: add returns a + b"]
    assert got["not_verified"] == ["the cli path - no cli in this repo"]
    assert got["assumed"] == ["ints only | why: the task says integers"
                              " | if wrong: floats round"]
    assert got["doubts"] == ["sub still returns a + b"]
    assert got["must_not_miss"] == ["TASK.md:3 - amounts are exact decimals,"
                                    " never floats"]
    assert got["tried"] == []
    assert got["read"] == ["calc.py:1-4 - the whole module"]
    assert got["other"] == {}


def test_an_assumed_item_keeps_its_labelled_lines_and_prints_its_labels():
    text = BLOCK.replace(
        "- ints only | why: the task says integers | if wrong: floats round\n",
        "- ints only\n  why: the task says integers\n  if wrong: floats round\n"
        "- the log stays as it is\n  - why: nothing asks for a change\n")
    got = handoff.parse(text)
    assert got["assumed"] == [
        "ints only\nwhy: the task says integers\nif wrong: floats round",
        "the log stays as it is\nwhy: nothing asks for a change"]
    assert got["other"] == {}
    assert summary.assumed(got["assumed"][0]) == (
        "ints only? why: the task says integers. if wrong: floats round.")
    assert summary.assumed(got["assumed"][1]) == (
        "the log stays as it is? why: nothing asks for a change.")


def test_an_assumed_item_in_the_older_piped_form_is_still_read():
    [item] = handoff.parse(BLOCK)["assumed"]
    assert summary.assumed(item) == (
        "ints only? why: the task says integers. if wrong: floats round.")


def test_the_next_step_is_handed_an_assumption_on_its_labelled_lines():
    text = BLOCK.replace(
        "- ints only | why: the task says integers | if wrong: floats round\n",
        "- ints only\n  why: the task says integers\n  if wrong: floats round\n")
    said = "\n".join(handoff.brief(Handoff("worker", "x\n" + text)))
    assert ("- ints only\n  why: the task says integers\n"
            "  if wrong: floats round") in said


def test_a_verified_item_is_split_into_claim_command_and_excerpt():
    [item] = handoff.parse(BLOCK)["verified"]
    assert item["claim"] == "1 passed"
    assert item["cmd"] == "python -m pytest -q test_calc.py"
    assert item["saw"] == "1 passed"
    assert item["backed"] == "unchecked"


def test_no_block_is_recorded_missing_never_invented():
    got = handoff.parse("- notes.md | changed\n")
    assert got["state"] == "missing"
    assert got["did"] == [] and got["verified"] == []


def test_a_block_with_no_end_is_unreadable_and_says_why():
    got = handoff.parse("HANDOFF\nDID:\n- a thing\n")
    assert got["state"] == "unreadable"
    assert "END HANDOFF" in got["why"]


def test_a_block_with_no_section_is_unreadable():
    got = handoff.parse("HANDOFF\nall good\nEND HANDOFF\n")
    assert got["state"] == "unreadable"


def test_the_last_block_wins_and_keys_survive_bullets_and_bold():
    text = ("HANDOFF\nDID:\n- old\nEND HANDOFF\n\nthen more\n\n"
            "**HANDOFF**\n- **DID:**\n  - new\n* VERIFIED: none\n"
            "Must-not-miss:\n- spec:1 - rule\n"
            "NEEDS: which is right?\n"
            "## END HANDOFF\n")
    got = handoff.parse(text)
    assert got["did"] == ["new"]
    assert got["verified"] == []
    assert got["must_not_miss"] == ["spec:1 - rule"]
    assert got["other"] == {"NEEDS": ["which is right?"]}


def test_a_bulleted_line_that_looks_like_a_heading_is_an_item():
    got = handoff.parse("HANDOFF\nDID:\n- Read: the spec first\n"
                        "- FAILS: assert 1 == 2\nEND HANDOFF\n")
    assert got["did"] == ["Read: the spec first", "FAILS: assert 1 == 2"]
    assert got["read"] == []


def test_a_continuation_line_joins_the_item_above_it():
    got = handoff.parse("HANDOFF\nDOUBTS:\n- the export\n  drops a row\n"
                        "END HANDOFF\n")
    assert got["doubts"] == ["the export drops a row"]


def test_the_answer_without_its_block_is_what_the_gates_and_the_saved_run_see():
    assert handoff.without("fixed it\n\n" + BLOCK) == "fixed it\n"
    assert handoff.without("no block here\n") == "no block here\n"
    assert handoff.without(BLOCK) == ""


# --- backing a VERIFIED claim against the step's own transcript -----------


def a_transcript(root, session, calls):
    """a cli transcript with one Bash call per (command, output)."""
    folder = root / "D--some-place"
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (cmd, out) in enumerate(calls):
        use = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t" + str(i), "name": "Bash",
             "input": {"command": cmd}}]}}
        result = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t" + str(i),
             "content": out}]}}
        lines.append(json.dumps(use))
        lines.append(json.dumps(result))
    (folder / (session + ".jsonl")).write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")
    return root


def test_a_claim_whose_command_and_output_are_in_the_transcript_is_backed(
        tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "PROJECTS", a_transcript(
        tmp_path / "p", "s-1",
        [("cd /work && python -m pytest -q test_calc.py 2>&1 | tail -1",
          "1 passed in 0.02s")]))
    block = handoff.back(handoff.parse(BLOCK),
                         handoff.transcript("s-1"))
    [item] = block["verified"]
    assert item["backed"] == "backed"


def a_tool_transcript(root, session, calls):
    """a cli transcript with one call per (tool, input, output)."""
    folder = root / "D--some-place"
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (name, given, out) in enumerate(calls):
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t" + str(i), "name": name,
             "input": given}]}}))
        lines.append(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t" + str(i),
             "content": out}]}}))
    (folder / (session + ".jsonl")).write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")
    return root


SEARCHED = [("Grep", {"pattern": "def mul", "path": "/w/place/calc.py",
                      "output_mode": "content", "-n": True},
             "/w/place/calc.py:4:def mul(a, b):"),
            ("Read", {"file_path": "\\w\\place\\TASK.md", "offset": 1,
                      "limit": 20},
             "     1\t# calc\n     3\tmul(a, b) returns a times b")]


@pytest.mark.parametrize("cited, saw", [
    ('Grep "def mul" calc.py', "calc.py:4:def mul(a, b):"),
    ("grep -n 'def mul' calc.py (the Grep tool)", "def mul(a, b)"),
    ("Read TASK.md", "mul(a, b) returns a times b"),
    ("Read tool on TASK.md lines 1-20", "returns a times b")])
def test_a_claim_backed_by_a_read_or_search_tool_call_is_backed(
        tmp_path, monkeypatch, cited, saw):
    monkeypatch.setattr(handoff, "PROJECTS", a_tool_transcript(
        tmp_path / "p", "s-1", SEARCHED))
    block = handoff.back(verified("- the spec says so\n  cmd: " + cited
                                  + "\n  saw: " + saw + "\n"),
                         handoff.transcript("s-1"))
    [item] = block["verified"]
    assert item["backed"] == "backed", item


@pytest.mark.parametrize("cited, saw", [
    ('Grep "def div" calc.py', "def div"),
    ('Grep "def mul" other.py', "def mul"),
    ("Read README.md", "mul(a, b) returns a times b"),
    ("Read TASK.md", "mul(a, b) returns a plus b")])
def test_a_claim_no_read_or_search_call_holds_stays_unbacked(
        tmp_path, monkeypatch, cited, saw):
    monkeypatch.setattr(handoff, "PROJECTS", a_tool_transcript(
        tmp_path / "p", "s-1", SEARCHED))
    block = handoff.back(verified("- the spec says so\n  cmd: " + cited
                                  + "\n  saw: " + saw + "\n"),
                         handoff.transcript("s-1"))
    [item] = block["verified"]
    assert item["backed"] == "unbacked", item


PRINTED = "  14\t    if not m or int(m.group(1)) < 1:\n  15\t        raise\n"
DATES = "def parse_month(s):\n    if not m or int(m.group(1)) < 1:\n        raise\n"


def a_place(tmp_path):
    for rel, text in (("place/dates.py", DATES),
                      ("place/cli.py", "LIMIT = 10\nSECRET_MODE = True\n")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


@pytest.mark.parametrize("command, cited", [
    ("cat -n place/dates.py place/cli.py", "Read place/dates.py"),
    ("cat -n place/dates.py place/cli.py", "Read dates.py"),
    ("cd {w} && cat {w}/place/dates.py | head -40", "Read place/dates.py"),
    ("cd {w}/place && cat -n dates.py", "Read place/dates.py"),
    ("sed -n 10,20p place/dates.py", "Read `place/dates.py`")])
def test_a_read_line_is_backed_by_the_shell_call_that_printed_that_file(
        tmp_path, command, cited):
    place = a_place(tmp_path)
    command = command.format(w=str(place).replace("\\", "/"))
    block = verified("- the month is checked\n  cmd: " + cited
                     + "\n  saw: if not m or int(m.group(1)) < 1\n")
    [item] = handoff.back(block, [(command, PRINTED)], place)["verified"]
    assert (item["backed"], item["by"]) == ("backed", "read"), item


@pytest.mark.parametrize("command, printed, saw", [
    ("cat -n place/dates.py place/cli.py", PRINTED + "SECRET_MODE = True\n",
     "SECRET_MODE = True"),
    ("cat place/dates.py; echo 'LIMIT = 99'", PRINTED + "LIMIT = 99\n",
     "LIMIT = 99"),
    ("cat place/dates.py | sed 's/< 1/< 0/'", PRINTED.replace("< 1", "< 0"),
     "int(m.group(1)) < 0"),
    ("cat > t.sh <<'EOF'\ncat place/dates.py\nEOF\necho 'LIMIT = 99'",
     "LIMIT = 99\n", "LIMIT = 99")])
def test_a_read_line_is_held_to_the_file_it_names_not_the_rest_of_the_call(
        tmp_path, command, printed, saw):
    place = a_place(tmp_path)
    block = verified("- the month is checked\n  cmd: Read place/dates.py\n"
                     "  saw: " + saw + "\n")
    for where in (place, None):
        [item] = handoff.back(block, [(command, printed)], where)["verified"]
        assert item["backed"] == "unbacked", (where, item)


def test_a_read_line_with_no_place_to_hold_its_file_to_stays_unbacked():
    block = verified("- the month is checked\n  cmd: Read place/dates.py\n"
                     "  saw: if not m or int(m.group(1)) < 1\n")
    [item] = handoff.back(block, [("cat -n place/dates.py", PRINTED)])[
        "verified"]
    assert item["backed"] == "unbacked", item


@pytest.mark.parametrize("command, cited", [
    ("cat -n place/dates.py place/cli.py", "Read place/money.py"),
    ('grep -n "if not m" place/dates.py', "Read place/dates.py"),
    ("cat place/dates.py > copy.py && cat place/cli.py", "Read place/dates.py"),
    ("cat -n place/dates.py", "Read via sed -n 10,20p place/dates.py"),
    ("cat -n place/dates.py place/cli.py", "Read place/dates.py place/cli.py"),
    ("cat -n place/dates.py", "read the file place/dates.py")])
def test_a_read_line_no_shell_call_printed_that_file_for_stays_unbacked(
        command, cited):
    block = verified("- the month is checked\n  cmd: " + cited
                     + "\n  saw: if not m or int(m.group(1)) < 1\n")
    [item] = handoff.back(block, [(command, PRINTED)])["verified"]
    assert item["backed"] == "unbacked", item


def test_a_read_line_whose_excerpt_the_printed_file_does_not_show_is_unbacked():
    block = verified("- the month is checked\n  cmd: Read place/dates.py\n"
                     "  saw: if not m or int(m.group(1)) < 0\n")
    [item] = handoff.back(block, [("cat -n place/dates.py", PRINTED)])[
        "verified"]
    assert item["backed"] == "unbacked"
    assert "does not show" in item["why"]


@pytest.mark.parametrize("calls, cited, saw, by", [
    ([("cd /w && python -m pytest -q", "1 passed in 0.02s")],
     "python -m pytest -q", "1 passed", "command"),
    ([("python - <<'EOF'\nx = 1\nprint(x)\nEOF", "1")],
     "x = 1; print(x)", "1", "stdin")])
def test_a_backed_claim_keeps_the_kind_of_call_that_backs_it(
        tmp_path, monkeypatch, calls, cited, saw, by):
    monkeypatch.setattr(handoff, "PROJECTS", a_transcript(
        tmp_path / "p", "s-1", calls))
    block = handoff.back(verified("- it holds\n  cmd: " + cited
                                  + "\n  saw: " + saw + "\n"),
                         handoff.transcript("s-1"))
    [item] = block["verified"]
    assert (item["backed"], item["by"]) == ("backed", by), item
    assert handoff.said(item).endswith("-> backed by " + by)


def test_a_claim_a_read_call_backs_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "PROJECTS", a_tool_transcript(
        tmp_path / "p", "s-1", SEARCHED))
    block = handoff.back(verified("- the spec says so\n  cmd: Read TASK.md"
                                  "\n  saw: returns a times b\n"),
                         handoff.transcript("s-1"))
    [item] = block["verified"]
    assert (item["backed"], item["by"]) == ("backed", "read")
    assert handoff.said(item).endswith("-> backed by read")


def test_a_claim_the_file_it_quotes_backs_says_so(tmp_path):
    (tmp_path / "TASK.md").write_text("# task\namounts are exact decimals\n",
                                      encoding="utf-8")
    block = handoff.back(verified('- TASK.md:2 "amounts are exact'
                                  ' decimals"\n'), None)
    [item] = handoff.to_files(block, tmp_path)["verified"]
    assert (item["backed"], item["by"]) == ("backed", "file")


def test_a_claim_nothing_held_names_no_kind(tmp_path, monkeypatch):
    block = handoff.back(verified("- it holds\n  cmd: python -m pytest -q"
                                  "\n  saw: 1 passed\n"), None)
    [item] = block["verified"]
    assert item["by"] is None
    assert handoff.said(item).endswith("-> unchecked: no transcript for this"
                                       " step")


def test_the_ladder_reports_the_backed_lines_per_kind():
    from agentweft.bench import ladder

    text = "\n".join([
        "# demo demo-1: done", "", "## the one decision", "- none", "",
        "## tests and checks", "- worker.md: PASS command - exit 0 (pytest)",
        "- worker verified: a | cmd: pytest | saw: 1 passed -> backed by"
        " command", "- worker verified: b | cmd: Read a.py | saw: x -> backed"
        " by read", "- worker verified: c | cmd: Read b.py | saw: y -> backed"
        " by read", "", "## run", ""])
    scored = ladder.score(text)
    assert scored["backing"] == {"command": 1, "stdin": 0, "read": 2,
                                 "file": 0, "not named": 0}
    point = [p for p in scored["points"] if p["point"] == "checks"][0]
    assert "by command 1, read 2" in point["line"]
    assert "1 of 3 by a command alone" in point["line"]
    report = ladder.table([scored])
    assert "backed by command 1, read 2" in report


def test_a_claim_with_no_such_call_is_unbacked(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "PROJECTS", a_transcript(
        tmp_path / "p", "s-1", [("git status", "clean")]))
    block = handoff.back(handoff.parse(BLOCK), handoff.transcript("s-1"))
    [item] = block["verified"]
    assert item["backed"] == "unbacked"
    assert "no such command" in item["why"]


def test_a_command_that_ran_but_printed_something_else_is_unbacked(
        tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "PROJECTS", a_transcript(
        tmp_path / "p", "s-1",
        [("python -m pytest -q test_calc.py", "1 failed in 0.02s")]))
    block = handoff.back(handoff.parse(BLOCK), handoff.transcript("s-1"))
    [item] = block["verified"]
    assert item["backed"] == "unbacked"
    assert "does not show" in item["why"]


def test_a_claim_that_names_no_command_is_unbacked():
    block = handoff.parse("HANDOFF\nVERIFIED:\n- all 40 tests pass\n"
                          "END HANDOFF\n")
    [item] = handoff.back(block, [("x", "y")])["verified"]
    assert item["backed"] == "unbacked" and "no command" in item["why"]


def verified(lines):
    return handoff.parse("HANDOFF\nVERIFIED:\n" + lines + "END HANDOFF\n")


def test_a_claim_quoting_a_file_line_that_is_not_there_is_unbacked(tmp_path):
    (tmp_path / "TASK.md").write_text("# task\namounts are exact decimals\n",
                                      encoding="utf-8")
    block = handoff.back(verified('- TASK.md:2 "amounts are rounded to'
                                  ' cents"\n'), None)
    [item] = handoff.to_files(block, tmp_path)["verified"]
    assert item["backed"] == "unbacked"
    assert '"amounts are rounded to cents"' in item["why"]
    assert "TASK.md:2" in item["why"]


def test_a_claim_quoting_its_file_line_is_backed_by_the_file(tmp_path):
    (tmp_path / "TASK.md").write_text("# task\namounts are exact decimals\n",
                                      encoding="utf-8")
    block = handoff.back(verified('- TASK.md:2 "amounts are exact'
                                  ' decimals"\n'), [("x", "y")])
    [item] = handoff.to_files(block, tmp_path)["verified"]
    assert item["backed"] == "backed"


def test_a_piped_command_on_its_own_line_is_kept_whole_and_backed():
    block = verified("- the suite is green\n"
                     "  cmd: python -m pytest -q | tail -5\n"
                     "  saw: 5 passed\n")
    [item] = block["verified"]
    assert item["claim"] == "the suite is green"
    assert item["cmd"] == "python -m pytest -q | tail -5"
    assert item["saw"] == "5 passed"
    [item] = handoff.back(block, [
        ("cd /w && python -m pytest -q | tail -5", "5 passed in 0.1s")])[
        "verified"]
    assert item["backed"] == "backed"


def test_an_old_one_line_claim_with_a_piped_command_still_parses_whole():
    [item] = verified("- green | cmd: python -m pytest -q | tail -5"
                      " | saw: 5 passed\n")["verified"]
    assert item["claim"] == "green"
    assert item["cmd"] == "python -m pytest -q | tail -5"
    assert item["saw"] == "5 passed"


def test_each_excerpt_is_matched_alone_and_the_missing_one_is_named():
    block = verified("- green and quiet\n"
                     "  cmd: python -m pytest -q\n"
                     "  saw: 5 passed\n"
                     "  saw: 0 warnings\n")
    [item] = handoff.back(block, [("python -m pytest -q",
                                   "5 passed, 2 warnings in 0.1s")])[
        "verified"]
    assert item["backed"] == "unbacked"
    assert item["why"].endswith("does not show 0 warnings")
    old = verified('- green | cmd: python -m pytest -q'
                   ' | saw: "5 passed" / "1 skipped"\n')
    [item] = handoff.back(old, [("python -m pytest -q",
                                 "5 passed, 1 skipped in 0.1s")])["verified"]
    assert item["backed"] == "backed"


CHECKED = [("sh check.sh", "== since [x]\r\nerror: invalid time: x\r\nexit 2\n"
                           "== until [y]\r\nexit 0\n"),
           ("sh other.sh", "rate a / b\n")]


@pytest.mark.parametrize("saw", [
    "== since [x] / error: invalid time: x / exit 2",
    "invalid time: x / exit 2",
    "exit 2 / == until",
    "rate a / b"])
def test_a_saw_of_consecutive_output_lines_joined_by_a_slash_is_backed(saw):
    block = verified("- bad times are refused\n  cmd: sh\n  saw: " + saw
                     + "\n")
    [item] = handoff.back(block, CHECKED)["verified"]
    assert item["backed"] == "backed", item


@pytest.mark.parametrize("saw", [
    "== since [x] / exit 2",
    "error: invalid time: x / == since [x]",
    "== since / error: invalid time: x",
    "== since [x] / error: invalid / exit 2",
    "exit 0 / rate a",
    "exit 2 /  / == until",
    "ime: x / exit 2",
    "exit 2 / == unt"])
def test_a_saw_whose_lines_are_not_consecutive_in_one_call_stays_unbacked(saw):
    block = verified("- bad times are refused\n  cmd: sh\n  saw: " + saw
                     + "\n")
    [item] = handoff.back(block, CHECKED)["verified"]
    assert item["backed"] == "unbacked", item
    assert item["why"].endswith("does not show " + saw)


DIFFED = [("git diff", "@@ -41,6 +41,10 @@ x\n y\n+  With x\n"),
          ("git log", "+  With z\n")]


@pytest.mark.parametrize("saw", [
    "@@ -41,6 +41,10 @@ ... +  With x",
    "@@ -41,6 ... y ... With x"])
def test_a_saw_cut_with_dots_is_backed_by_its_pieces_in_order(saw):
    block = verified("- the diff only adds\n  cmd: git\n  saw: " + saw + "\n")
    [item] = handoff.back(block, DIFFED)["verified"]
    assert item["backed"] == "backed", item


@pytest.mark.parametrize("saw", [
    "+  With x ... @@ -41,6 +41,10 @@",
    "@@ -41,6 +41,10 @@ ... +  With q",
    "@@ -41,6 +41,10 @@ ... With z",
    "y ... y",
    "@@ -41,6 +41,10 @@ ...  ... With x"])
def test_a_saw_cut_with_dots_whose_pieces_one_call_does_not_hold_in_order(saw):
    block = verified("- the diff only adds\n  cmd: git\n  saw: " + saw + "\n")
    [item] = handoff.back(block, DIFFED)["verified"]
    assert item["backed"] == "unbacked", item
    assert item["why"].endswith("does not show " + saw)


RAN = [("cd /w && python -m pytest -q tests/test_calc.py",
        "5 passed in 0.1s\n0 warnings")]


@pytest.mark.parametrize("pointer", ["(same command)", "same as above",
                                     "(same as above)", "as above",
                                     "see above", "same cmd as above",
                                     "the same command as before"])
def test_a_pointer_in_other_words_than_the_prompt_asks_for_names_nothing(
        pointer):
    block = verified("- the suite is green\n"
                     "  cmd: python -m pytest -q tests/test_calc.py\n"
                     "  saw: 5 passed\n"
                     "- nothing warns\n"
                     "  cmd: " + pointer + "\n"
                     "  saw: 0 warnings\n")
    first, second = handoff.back(block, RAN)["verified"]
    assert second["cmd"] == pointer
    assert (first["backed"], second["backed"]) == ("backed", "unbacked")


@pytest.mark.parametrize("pointer", ["(same command as above)",
                                     "same command as above",
                                     "Same command as above."])
def test_a_verified_line_pointing_at_the_command_above_is_matched_as_it(
        pointer):
    block = verified("- the suite is green\n"
                     "  cmd: python -m pytest -q tests/test_calc.py\n"
                     "  saw: 5 passed\n"
                     "- nothing warns\n"
                     "  cmd: " + pointer + "\n"
                     "  saw: 0 warnings\n")
    first, second = handoff.back(block, RAN)["verified"]
    assert second["cmd"] == "python -m pytest -q tests/test_calc.py"
    assert first["backed"] == "backed" and second["backed"] == "backed"


BY_HAND = [("cd /w && python - <<'EOF'\nfrom calc import mul\n"
            "print(mul(2, 'x'))\nEOF", "TypeError: can't multiply")]


@pytest.mark.parametrize("cited", [
    "python - <<'EOF'; from calc import mul; print(mul(2, \"x\")); EOF",
    "python - <<EOF from calc import mul; print(mul(2, 'x')) EOF",
    "from calc import mul; print(mul(2, 'x'))"])
def test_a_script_fed_on_stdin_the_transcript_holds_backs_its_claim(cited):
    block = verified("- mul refuses a string\n"
                     "  cmd: " + cited + "\n"
                     "  saw: TypeError\n")
    [item] = handoff.back(block, BY_HAND)["verified"]
    assert item["backed"] == "backed", item


@pytest.mark.parametrize("cited", [
    "python - <<'EOF'; from calc import mul; print(mul(3, 'x')); EOF",
    "(harness that calls mul with a string)",
    "node - <<'EOF'; from calc import mul; print(mul(2, 'x')); EOF"])
def test_a_script_on_stdin_the_transcript_does_not_hold_stays_unbacked(cited):
    block = verified("- mul refuses a string\n"
                     "  cmd: " + cited + "\n"
                     "  saw: TypeError\n")
    [item] = handoff.back(block, BY_HAND)["verified"]
    assert item["backed"] == "unbacked", item


def test_a_check_is_asked_for_as_a_call_of_its_own_and_a_stand_in_is_a_cut():
    words = " ".join(resolver.shared_rules().split())
    assert ("run a check as a call of its own, not at the end of a call that"
            " writes or edits a file") in words
    assert "`(test body)`" in words and "a cut like `...`" in words


WROTE = [("cat >> tests/test_x.py <<'EOF'\ndef test_x():\n"
          "    assert mul(2, 3) == 6\nEOF\npython -m pytest -q tests/test_x.py",
          "1 passed in 0.1s")]


@pytest.mark.parametrize("cited", [
    "cat >> tests/test_x.py <<'EOF' (test body) EOF; python -m pytest -q"
    " tests/test_x.py",
    "cat >> tests/test_x.py <<'EOF'; (three new tests); EOF; python -m pytest"
    " -q tests/test_x.py"])
def test_a_stand_in_for_the_file_a_call_wrote_stays_unbacked(cited):
    block = verified("- the new test passes\n  cmd: " + cited
                     + "\n  saw: 1 passed\n")
    [item] = handoff.back(block, WROTE)["verified"]
    assert item["backed"] == "unbacked", item


def test_a_saw_is_asked_for_as_printed_text_and_a_silent_check_to_print():
    words = " ".join(resolver.shared_rules().split())
    assert "a `saw:` is text the call printed, copied" in words
    assert "`git diff --quiet -- <file>; echo $?`" in words


QUIET = [("git diff --quiet -- calc.py", ""),
         ("git diff --quiet -- calc.py; echo $?", "0\n")]


@pytest.mark.parametrize("cited, saw", [
    ("git diff --quiet -- calc.py", "(empty output)"),
    ("git diff --quiet -- calc.py", "(no diff output for calc.py)")])
def test_a_saw_that_describes_an_empty_answer_stays_unbacked(cited, saw):
    block = verified("- calc.py is unchanged\n  cmd: " + cited + "\n  saw: "
                     + saw + "\n")
    [item] = handoff.back(block, QUIET[:1])["verified"]
    assert item["backed"] == "unbacked", item


def test_a_silent_check_made_to_print_its_answer_is_backed():
    block = verified("- calc.py is unchanged\n"
                     "  cmd: git diff --quiet -- calc.py; echo $?\n"
                     "  saw: 0\n")
    [item] = handoff.back(block, QUIET)["verified"]
    assert (item["backed"], item["by"]) == ("backed", "command"), item


LOOPED = [("cd /w && L=1\nfor a in 1 2; do echo $a; done", "1\n2\n"),
          ('python -c "\nimport sys\nprint(1)\n"', "1\n"),
          ('python -c "\nfor a in [7]:\n    print(a)\n"', "7\n"),
          ("grep -c ';' notes.md", "1\n")]


@pytest.mark.parametrize("cited, saw", [
    ("cd /w && L=1; for a in 1 2; do echo $a; done", "2"),
    ("L=1;  for a in 1 2; do echo $a; done", "2"),
    ('python -c "import sys; print(1)"', "1"),
    ('python -c "for a in [7]:;     print(a)"', "7")])
def test_a_command_cited_with_a_semicolon_for_each_line_break_is_backed(
        cited, saw):
    block = verified("- it prints\n  cmd: " + cited + "\n  saw: " + saw + "\n")
    [item] = handoff.back(block, LOOPED)["verified"]
    assert (item["backed"], item["by"]) == ("backed", "command"), item


@pytest.mark.parametrize("cited", [
    "cd /w && L=3; for a in 1 2; do echo $a; done",
    "L=1; for a in 1 2; do echo $a; done; echo 3",
    'python -c "import sys; print(2)"',
    'python -c "import os; print(1)"',
    'python -c "for a in [8]:;     print(a)"',
    "grep -c '' notes.md"])
def test_a_command_with_a_changed_token_beside_its_breaks_stays_unbacked(
        cited):
    block = verified("- it prints\n  cmd: " + cited + "\n  saw: 1\n")
    [item] = handoff.back(block, LOOPED)["verified"]
    assert item["backed"] == "unbacked", item


def test_the_hand_runs_reviewer_is_asked_for_each_command_in_full():
    words = " ".join((Path(__file__).resolve().parents[1] / "flows"
                      / "build-feature" / "reviewer-runs.md").read_text(
        encoding="utf-8").split())
    assert "each command you ran by hand" in words
    assert "never a name for it" in words


def prompt_words(*parts):
    return " ".join((Path(__file__).resolve().parents[1].joinpath(*parts))
                    .read_text(encoding="utf-8").split())


def test_the_same_command_again_is_asked_for_in_the_words_the_runner_reads():
    shared = prompt_words("agentweft", "fragments", "handoff.md")
    by_hand = prompt_words("flows", "build-feature", "reviewer-runs.md")
    for words in (shared, by_hand):
        assert "the same command again included" not in words
        [asked] = re.findall(r"`cmd: (same[^`]*)`", words)
        assert handoff.ABOVE.match(asked), asked
    assert "write every `cmd:` out in full" in shared


def test_a_pointer_with_a_note_after_it_is_not_read_as_the_command_above():
    block = verified("- the suite is green\n"
                     "  cmd: python -m pytest -q tests/test_calc.py\n"
                     "  saw: 5 passed\n"
                     "- nothing warns\n"
                     "  cmd: same heredoc command as above, run once\n"
                     "  saw: 0 warnings\n")
    first, second = handoff.back(block, RAN)["verified"]
    assert second["cmd"] == "same heredoc command as above, run once"
    assert (first["backed"], second["backed"]) == ("backed", "unbacked")


def test_a_pointer_with_no_command_above_it_stays_unbacked():
    block = verified("- nothing warns\n"
                     "  cmd: (same command as above)\n"
                     "  saw: 0 warnings\n")
    [item] = handoff.back(block, RAN)["verified"]
    assert item["backed"] == "unbacked"


@pytest.mark.parametrize("cut", ["python -m pytest -q ... tests/test_calc.py",
                                 "python -m pytest -q tests/test_calc.py ...",
                                 'python -c "..."',
                                 "python -m pytest " + chr(0x2026)])
def test_a_shortened_command_is_marked_shortened_not_unbacked(cut):
    block = verified("- the suite is green\n"
                     "  cmd: " + cut + "\n"
                     "  saw: 5 passed\n")
    [item] = handoff.back(block, RAN)["verified"]
    assert item["backed"] == "shortened"
    assert "in full" in item["why"]


@pytest.mark.parametrize("whole", ["go test ./...", "git diff main...HEAD"])
def test_dots_that_are_part_of_a_command_are_not_a_shortening(whole):
    block = verified("- green\n  cmd: " + whole + "\n  saw: ok\n")
    [item] = handoff.back(block, [(whole, "ok")])["verified"]
    assert item["backed"] == "backed"


def test_the_handoff_names_a_shortened_command_apart_from_unbacked_claims():
    block = handoff.back(verified("- the suite is green\n"
                                  "  cmd: python -m pytest ... -q\n"
                                  "  saw: 5 passed\n"), RAN)
    lines = summary.build("r1", "flow", "t", [summary.a_pass(
        "worker.md", "worker", 1.0, block, [], False, "ok", "")],
        {"git": False}, [], "")
    said = "\n".join(lines)
    assert "claims the record does not show" not in said
    assert ("- shortened, so not held to the record: worker: the suite is"
            " green (python -m pytest ... -q)") in said


def test_no_transcript_leaves_a_claim_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(handoff, "PROJECTS", tmp_path / "nothing")
    assert handoff.transcript("s-9") is None
    [item] = handoff.back(handoff.parse(BLOCK), None)["verified"]
    assert item["backed"] == "unchecked"


# --- the prompts ask for it ----------------------------------------------


def composed(flow):
    """every step the flow file declares, a switched-off judge included."""
    from agentweft.flow import reader
    cfg = runner.config(flow)
    declared = reader.read((runner.flow_path(flow) / "flow.yaml").read_text(
        encoding="utf-8"))
    by_role = resolver.resolve(declared, runner.flow_path(flow),
                               cfg.promises.as_prompt())
    return {s["role"]: prompts.load_prompt(flow, s["prompt"],
                                           by_role[s["role"]], s["role"])
            for s in declared["steps"]}


@pytest.mark.parametrize("flow,role", [
    ("fix-with-test", "worker"), ("fix-with-test", "patcher"),
    ("fix-with-test", "verify"), ("build-feature", "planner"),
    ("build-feature", "reviewer"), ("weekly-digest", "merge")])
def test_every_role_is_asked_for_the_block_and_not_told_to_hide_its_work(
        flow, role):
    prompt = composed(flow)[role]
    assert "do not list what you changed" not in prompt
    assert "do not explain your reasoning" not in prompt
    assert 'print "nothing to report" and stop' not in prompt
    assert "END HANDOFF" in prompt
    for key in ("DID:", "VERIFIED:", "NOT VERIFIED:", "ASSUMED:", "DOUBTS:",
                "MUST NOT MISS:", "TRIED:", "READ:"):
        assert key in prompt, key
    assert "cmd:" in prompt and "saw:" in prompt
    assert "| cmd:" not in prompt and "| saw:" not in prompt
    assert "write every `cmd:` out in full" in prompt


def test_the_next_step_gets_the_block_first_and_told_whose_account_it_is():
    h = Handoff("worker", "fixed it\n\n" + BLOCK)
    text = h.as_prompt()
    assert text.index("worker handed over") < text.index("fixed it")
    assert text.index("TASK.md:3 - amounts are exact decimals") \
        < text.index("fixed it")
    assert "not instructions" in text
    assert "re-open only what you change or doubt" in text
    assert "calc.py:1-4 - the whole module" in text
    # the block itself is not pasted a second time under the raw output
    assert text.count("END HANDOFF") == 0


def test_constraints_from_every_earlier_step_travel_to_the_next():
    h = Handoff("patcher", "patched\n", carried=[
        ("worker", "TASK.md:3 - amounts are exact decimals")])
    assert "TASK.md:3 - amounts are exact decimals" in h.as_prompt()
    assert "(from worker)" in h.as_prompt()


KEPT = "TASK.md:3 - amounts are exact decimals"


def kept_by(*roles):
    """-> a reviewer's Handoff that keeps KEPT, as every role before it did."""
    return Handoff(roles[-1], "HANDOFF\nMUST NOT MISS:\n- " + KEPT
                   + "\nEND HANDOFF\n",
                   carried=[(r, KEPT) for r in roles[:-1]])


def test_a_line_three_roles_keep_reaches_the_next_step_once_with_all_three():
    text = kept_by("worker", "tester", "reviewer").as_prompt()
    assert text.count(KEPT) == 1, text
    assert "- " + KEPT + " (from worker, tester, reviewer)" in text


def test_a_line_three_roles_keep_is_carried_forward_once_with_all_three():
    passes = [summary.a_pass(r + ".md", r, 1.0, kept_by(r).block, [], False,
                             "ok", "") for r in ("worker", "tester", "reviewer")]
    lines = summary.build("f-1", "f", "t", passes, {"git": False}, [],
                          "1 call")
    carry = lines[lines.index("## carry forward"):]
    carry = carry[:carry.index("")]
    assert [l for l in carry if KEPT in l] == [
        "- keep: " + KEPT + " (worker, tester, reviewer)"]


def test_a_missing_block_is_said_so_to_the_next_step():
    assert "handed over no HANDOFF block" in Handoff("worker", "x\n").as_prompt()


ASKS = ("HANDOFF\nDID:\n- x\nQUESTION: does LF print raw? TASK.md:11\n"
        "RECOMMEND: escape\nSIZE: one line\nEND HANDOFF")
ASKED = "does LF print raw? TASK.md:11"


def test_the_next_step_is_handed_the_question_the_step_before_asked():
    text = Handoff("planner", ASKS).as_brief()
    assert "- " + ASKED + " (from planner)" in text, text
    assert "questions already asked" in text


def test_a_question_reaches_a_step_two_away_once_with_every_role_that_asked():
    text = Handoff("tester", ASKS, asked=[("planner", ASKED)]).as_prompt()
    assert text.count(ASKED) == 1, text
    assert "- " + ASKED + " (from planner, tester)" in text
    later = Handoff("worker", "x\n", asked=[("planner", ASKED)]).as_prompt()
    assert "- " + ASKED + " (from planner)" in later, later


def test_a_question_of_none_is_not_handed_on():
    text = Handoff("planner", ASKS.replace(
        "does LF print raw? TASK.md:11", "none")).as_brief()
    assert "questions already asked" not in text


def test_a_question_travels_through_the_runner_to_the_step_two_away(
        tmp_path, monkeypatch):
    seen = []
    real = engine.call

    def spy(prompt, timeout=None, cap=3, step="?", provider=None):
        seen.append((step, prompt))
        return real(prompt, timeout, cap, step, provider)

    monkeypatch.setattr(engine, "call", spy)
    a_fake_flow(tmp_path, monkeypatch, "asks-on",
                [("planner", "planned\n\n" + ASKS + "\n"),
                 ("worker", WORKER), ("reviewer", REVIEWER)])
    engine.main()
    prompts_of = dict(seen)
    assert ASKED + " (from planner)" in prompts_of["reviewer.md"]


# --- through the runner ---------------------------------------------------


def a_fake_flow(tmp_path, monkeypatch, name, replies, extra=""):
    """a flow of fake-provider steps answering `replies` in order, one role
    per (role, reply) pair, run through main() the way it is typed."""
    flow = tmp_path / "flows" / name
    flow.mkdir(parents=True)
    body = "name: " + name + "\nsteps:\n"
    for role, reply in replies:
        body = (body + "  - role: " + role + "\n    prompt: " + role + ".md\n"
                "    provider:\n      provider: fake\n"
                "      reply: " + json.dumps(reply) + "\n")
        (flow / (role + ".md")).write_text("# " + role + "\n\ndo it.\n",
                                           encoding="utf-8")
    (flow / "flow.yaml").write_text(body + extra + "provider:\n"
                                    "  provider: fake\n", encoding="utf-8")
    (flow / "instructions.md").write_text("the " + name + " flow.\n",
                                          encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force",
                                      "--flows", "flows"])


def run_dir(tmp_path):
    return sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]


def steps_of(folder):
    return [json.loads(l) for l in (folder / "steps.jsonl")
            .read_text(encoding="utf-8").split("\n") if l.strip()]


WORKER = ("- notes.md | changed\n\nHANDOFF\nDID:\n- notes.md: the plan moved\n"
          "VERIFIED:\n- none\nNOT VERIFIED:\n- none\nASSUMED:\n- none\n"
          "DOUBTS:\n- rent.md may be stale\nMUST NOT MISS:\n"
          "- spec.md:2 - never drop a dated line\nTRIED:\n- none\nREAD:\n"
          "- notes.md:1-9 - the dates\nEND HANDOFF\n")
REVIEWER = ("VERDICT: ok\n\nfine\n\nHANDOFF\nDID:\n- checked notes.md\n"
            "VERIFIED:\n- every date kept | cmd: grep -c 2026 notes.md"
            " | saw: 3\nNOT VERIFIED:\n- none\nASSUMED:\n- none\nDOUBTS:\n"
            "- none\nMUST NOT MISS:\n- none\nTRIED:\n- none\nREAD:\n"
            "- notes.md:1-9 - the dates\nEND HANDOFF\n")


def test_a_two_step_run_records_both_blocks_and_writes_a_handoff_listing_them(
        tmp_path, monkeypatch, capsys):
    a_fake_flow(tmp_path, monkeypatch, "two", [("worker", WORKER),
                                               ("reviewer", REVIEWER)])
    assert engine.main() == 0
    folder = run_dir(tmp_path)
    first, second = steps_of(folder)
    assert first["handoff"]["state"] == "present"
    assert first["handoff"]["doubts"] == ["rent.md may be stale"]
    assert second["handoff"]["state"] == "present"
    assert second["handoff"]["verified"][0]["backed"] == "unchecked"
    note = (folder / summary.FILE).read_text(encoding="utf-8")
    assert note.startswith("# two " + folder.name + ": done")
    assert "notes.md: the plan moved" in note
    assert "rent.md may be stale" in note
    assert "spec.md:2 - never drop a dated line" in note
    assert "every date kept" in note and "unchecked" in note
    assert "not a git checkout" in note
    # the run's last console output is the top of the file, then its path
    printed = capsys.readouterr().out.rstrip("\n").split("\n")
    assert printed[-1] == "handoff: " + str(folder / summary.FILE)
    assert any(l.startswith("# two " + folder.name + ": done")
               for l in printed)
    journal = (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")
    assert journal.rstrip("\n").endswith(folder.name + "/" + summary.FILE)


def test_a_step_without_the_block_is_recorded_missing(tmp_path, monkeypatch):
    a_fake_flow(tmp_path, monkeypatch, "bare", [("worker", "- a | b\n"),
                                                ("reviewer", REVIEWER)])
    engine.main()
    folder = run_dir(tmp_path)
    first, second = steps_of(folder)
    assert first["handoff"] == handoff.parse("")
    assert first["handoff"]["state"] == "missing"
    note = (folder / summary.FILE).read_text(encoding="utf-8")
    assert "handoff missing: worker.md" in note
    # recorded, never a failure by default
    assert first["outcome"] == "ok" and second["outcome"] == "ok"


def test_the_saved_run_and_the_gates_see_the_answer_without_its_block(
        tmp_path, monkeypatch):
    a_fake_flow(tmp_path, monkeypatch, "gated", [("worker", WORKER)])
    flow = tmp_path / "flows" / "gated" / "flow.yaml"
    flow.write_text(flow.read_text(encoding="utf-8").replace(
        "    provider:\n      provider: fake\n      reply:",
        "    gates:\n      - gate: length\n        max_lines: 1\n"
        "    provider:\n      provider: fake\n      reply:"),
        encoding="utf-8")
    assert engine.main() == 0
    folder = run_dir(tmp_path)
    [line] = steps_of(folder)
    assert line["gates"] == [{"gate": "length", "ok": True,
                              "detail": "1 lines"}]
    [saved] = [p for p in (tmp_path / "runs").iterdir()
               if p.is_file() and p.name.startswith("gated-")]
    assert saved.read_text(encoding="utf-8") == "- notes.md | changed\n"
    # the step file keeps the whole answer, block included
    assert "END HANDOFF" in (folder / "worker.md").read_text(encoding="utf-8")


def test_a_run_that_parks_still_writes_the_handoff_with_the_park_reason(
        tmp_path, monkeypatch, capsys):
    a_fake_flow(tmp_path, monkeypatch, "parks",
                [("worker", WORKER), ("reviewer", REVIEWER)])
    flow = tmp_path / "flows" / "parks" / "flow.yaml"
    flow.write_text(flow.read_text(encoding="utf-8").replace(
        "  - role: reviewer\n", "    pause: user\n  - role: reviewer\n"),
        encoding="utf-8")
    assert engine.main() == 2
    folder = run_dir(tmp_path)
    note = (folder / summary.FILE).read_text(encoding="utf-8")
    assert note.startswith("# parks " + folder.name + ": needs you: ruling at worker.md")
    assert "## needs you" in note
    assert "waiting for    user" in note
    assert "python run.py parks --resume " + folder.name in note
    assert "rent.md may be stale" in note
    printed = capsys.readouterr().out.rstrip("\n").split("\n")
    assert printed[-1] == "handoff: " + str(folder / summary.FILE)
    assert "## needs you" in printed


def test_a_gate_stop_and_a_budget_stop_write_the_handoff_too(tmp_path,
                                                             monkeypatch):
    a_fake_flow(tmp_path, monkeypatch, "stops",
                [("worker", WORKER), ("reviewer", "VERDICT: ok\n\nx\n")],
                extra="max_calls: 1\n")
    assert engine.main() == 2
    note = (run_dir(tmp_path) / summary.FILE).read_text(encoding="utf-8")
    assert ": needs you: budget at " in note.split("\n")[0]
    assert "call cap" in note


def test_a_needs_line_reaches_the_needs_you_section_before_any_gate(
        tmp_path, monkeypatch):
    asking = ("TEST: t.py\nNEEDS: keep the string or change it?\nCITES:\n"
              "- TASK.md:158 - a string with 2 decimals\nOPTIONS:\n"
              "- A: keep\n- B: change\n\nHANDOFF\nDID:\n- nothing changed\n"
              "END HANDOFF\n")
    a_fake_flow(tmp_path, monkeypatch, "asks", [("patcher", asking),
                                                ("verify", "PASS x\n")])
    flow = tmp_path / "flows" / "asks" / "flow.yaml"
    flow.write_text(flow.read_text(encoding="utf-8").replace(
        "    provider:\n      provider: fake\n      reply:",
        "    gates:\n      - gate: regex\n        pattern: \"^NEEDS:\"\n"
        "        present: false\n    provider:\n      provider: fake\n"
        "      reply:", 1), encoding="utf-8")
    assert engine.main() == 2
    note = (run_dir(tmp_path) / summary.FILE).read_text(encoding="utf-8")
    needs = note.split("## needs you\n")[1].split("\n## ")[0]
    assert "- patcher asks: keep the string or change it?" in needs
    assert "  cites: TASK.md:158 - a string with 2 decimals" in needs
    assert "  option: B: change" in needs
    # the gate would fail on the NEEDS line; the question stops the run first
    assert ": needs you: ruling at patcher.md" in note.split("\n")[0]


def test_the_next_prompt_starts_with_what_the_step_before_handed_over(
        tmp_path, monkeypatch):
    seen = []
    real = engine.call

    def spy(prompt, timeout=None, cap=3, step="?", provider=None):
        seen.append((step, prompt))
        return real(prompt, timeout, cap, step, provider)

    monkeypatch.setattr(engine, "call", spy)
    a_fake_flow(tmp_path, monkeypatch, "chain", [("worker", WORKER),
                                                 ("reviewer", REVIEWER)])
    engine.main()
    [(_, _), (step, prompt)] = seen
    assert step == "reviewer.md"
    tail = prompt[prompt.index("worker handed over"):]
    assert tail.index("spec.md:2 - never drop a dated line") \
        < tail.index("here is what worker produced")
    assert "END HANDOFF" not in tail


# --- what the runner knows comes from the runner ---------------------------


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                   encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == -1\n",
        encoding="utf-8")
    (where / "TASK.md").write_text("# task\n\nadd adds.\n", encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def test_changed_files_commits_and_edited_tests_come_from_git(tmp_path):
    place = a_repo(tmp_path / "repo")
    start = summary.tree(place)
    (place / "calc.py").write_text("def add(a, b):\n    return a + b\n",
                                   encoding="utf-8")
    git(place, "commit", "-qam", "fix add")
    (place / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")
    (place / "tests" / "test_new.py").write_text("def test_x():\n    pass\n",
                                                 encoding="utf-8")
    (place / "TASK.md").write_text("# task\n\nadd adds, exactly.\n",
                                   encoding="utf-8")
    got = start.changes()
    assert got["git"] is True
    assert [c[1] for c in got["commits"]] == ["fix add"]
    assert ("calc.py", 1, 1, "committed") in got["files"]
    assert ("tests/test_calc.py", 1, 1, "uncommitted") in got["files"]
    assert ("tests/test_new.py", 2, 0, "untracked") in got["files"]
    assert ("tests/test_calc.py", 1, 1) in got["tests_changed"]
    assert ("tests/test_new.py", 2, 0) not in got["tests_changed"]
    assert ("TASK.md", 1, 1) in got["spec_changed"]


def test_an_edited_pre_existing_test_is_unruled_unless_a_decision_names_it(
        tmp_path):
    place = a_repo(tmp_path / "repo")
    start = summary.tree(place)
    (place / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8")
    lines = summary.rulings(start.changes(), decisions.read(place))
    assert any("tests/test_calc.py" in l and "UNRULED" in l for l in lines)
    decisions.record(place, "tests/test_calc.py: the test was wrong, add adds",
                     "the task says so")
    lines = summary.rulings(start.changes(), decisions.read(place))
    assert any("tests/test_calc.py" in l and "ruling" in l
               and "the test was wrong" in l for l in lines)
    assert not any("UNRULED" in l for l in lines)


def test_a_pyc_under_tests_is_not_a_test_and_the_cause_line_reads_as_prose():
    assert summary.is_test("tests/test_x.py")
    assert not summary.is_test("tests/__pycache__/test_x.cpython-314.pyc")
    assert summary.cause("CAUSE: money.py:19 - rounds down") == \
        "cause: money.py:19 - rounds down"


def test_a_role_sent_back_has_the_did_lines_of_both_passes():
    first = handoff.parse("HANDOFF\nDID:\n- top=N keeps N rows\nEND HANDOFF\n")
    again = handoff.parse("HANDOFF\nDID:\n- a test for top past the end\n"
                          "- top=N keeps N rows\nEND HANDOFF\n")
    passes = [{"role": "worker", "block": first},
              {"role": "reviewer", "block": handoff.parse("")},
              {"role": "worker", "block": again}]
    assert summary.did_of(passes, "worker") == [
        "top=N keeps N rows", "a test for top past the end"]


def test_authority_claimed_with_no_ruling_on_record_is_flagged():
    blocks = [("patcher", handoff.parse(
        "HANDOFF\nDID:\n- changed the assertion, as agreed with the user\n"
        "END HANDOFF\n"))]
    got = summary.authority(blocks, [])
    assert got == ["patcher: \"as agreed\" - changed the assertion, as agreed"
                   " with the user"]
    assert summary.authority(blocks, [object()]) == []


def _doubt(text):
    return [("patcher", handoff.parse(
        "HANDOFF\nDOUBTS:\n- " + text + "\nEND HANDOFF\n"))]


def test_an_open_question_about_a_ruling_is_not_a_claim_of_one():
    for text in ("nobody has ruled on which format wins",
                 "the spec line has not been approved",
                 "no one approved this yet",
                 "the format needs a ruling",
                 "not as agreed with the user"):
        assert summary.authority(_doubt(text), []) == [], text


def test_a_claim_that_a_person_decided_is_flagged_once():
    got = summary.authority(_doubt("the user approved the new format"), [])
    assert got == ["patcher: \"the user approved\" - the user approved the"
                   " new format"]
    got = summary.authority(_doubt("as agreed, amounts stay strings"), [])
    assert got == ["patcher: \"as agreed\" - as agreed, amounts stay strings"]


def test_a_run_in_a_git_checkout_lists_what_changed_from_the_tree(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    fixed = "def add(a, b):\n    return a + b\n"
    a_fake_flow(tmp_path, monkeypatch, "treed", [("worker", WORKER)],
                extra="workdir: " + place.as_posix() + "\n")
    real = engine.Run.step

    def step(self, name, previous=engine.EMPTY, extra="", task=None):
        (place / "calc.py").write_text(fixed, encoding="utf-8")
        return real(self, name, previous=previous, extra=extra, task=task)

    monkeypatch.setattr(engine.Run, "step", step)
    assert engine.main() == 0
    note = (run_dir(tmp_path) / summary.FILE).read_text(encoding="utf-8")
    assert "calc.py +1 -1 (uncommitted)" in note
    assert "..HEAD: prints nothing" in note


# --- the fanned-out step ---------------------------------------------------


def test_the_blocks_of_a_fanned_out_step_are_merged_onto_its_line():
    a = handoff.parse("HANDOFF\nDID:\n- a\nMUST NOT MISS:\n- r1\nEND HANDOFF\n")
    b = handoff.parse("HANDOFF\nDID:\n- b\nEND HANDOFF\n")
    merged = handoff.merge([a, b])
    assert merged["state"] == "present"
    assert merged["did"] == ["a", "b"]
    assert merged["must_not_miss"] == ["r1"]
    partial = handoff.merge([a, handoff.parse("")])
    assert partial["state"] == "partial" and "1 of 2" in partial["why"]
    assert handoff.merge([handoff.parse(""), handoff.parse("")])["state"] \
        == "missing"


# --- the park section keeps saying what ran and what is left ----------------


def test_the_park_section_says_what_ran_what_is_left_and_how_to_carry_on():
    lines = park.lines("worker.md", "user", [("planner.md", 3),
                                             ("worker.md", 12)],
                       ["reviewer.md"], "python run.py demo --resume demo-1")
    text = "\n".join(lines)
    assert "waiting for    user" in text
    assert "stopped after  worker.md" in text
    assert "nothing failed." in text
    assert "  planner.md      3s" in text and "  reviewer.md" in text
    assert lines[-2] == "to carry on"
    assert lines[-1] == "  python run.py demo --resume demo-1"


def stopped_build(stopped, needs, changes=None):
    return summary.build("demo-1", "demo", "t", [summary.a_pass(
        "worker.md", "worker", 1.0, handoff.parse(WORKER), [], False,
        "ok", "")], changes or {"git": False}, [], "", stopped=stopped,
        needs=needs, command="python run.py demo --resume demo-1")


def not_done_of(lines):
    view = lines[:lines.index("## full record")]
    return view[view.index("## not done"):view.index("## product gaps")]


CHANGED = {"git": True, "commits": [], "start": None,
           "files": [("calc.py", 1, 1, "uncommitted"),
                     ("tests/test_calc.py", 4, 0, "untracked")]}


def test_a_park_says_in_a_line_of_its_own_what_is_left_to_run():
    needs = park.ruling("worker.md", "user", [("worker.md", 2)],
                        ["worker.md", "reviewer.md"],
                        "python run.py demo --resume demo-1", "which one?",
                        worked="")
    lines = stopped_build({"cause": stops.PARKED, "why": "which one?",
                           "at": "worker.md"}, needs, CHANGED)
    assert ("- not done: the run stopped at worker.md; left to run:"
            " worker.md, reviewer.md; the 2 files it changed are not taken"
            " as done") in not_done_of(lines)


def test_a_gate_stop_with_nothing_changed_says_so_and_what_is_left():
    needs = park.lines("worker.md", None, [("worker.md", 2)],
                       ["worker.md", "reviewer.md"],
                       "python run.py demo --resume demo-1",
                       why="regex failed", cause=stops.GATE)
    lines = stopped_build({"cause": stops.GATE, "why": "regex failed",
                           "at": "worker.md"}, needs,
                          dict(CHANGED, files=[]))
    assert ("- not done: the run stopped at worker.md; left to run:"
            " worker.md, reviewer.md; nothing in the tree changed") \
        in not_done_of(lines)


def test_a_stop_at_the_last_step_and_a_declined_one_say_what_is_not_done():
    needs = park.lines("reviewer.md", "user", [("reviewer.md", 2)], [],
                       "python run.py demo --resume demo-1")
    lines = stopped_build({"cause": stops.PARKED, "why": "",
                           "at": "reviewer.md"}, needs)
    assert ("- not done: the run stopped at reviewer.md with no step left"
            " to run after it; what carries it on is under needs you") \
        in not_done_of(lines)
    needs = park.refused("worker.md", "TASK.md:3 - no network", [])
    lines = stopped_build({"cause": stops.DECLINED, "why": "TASK.md:3",
                           "at": "worker.md"}, needs)
    assert ("- not done: the work the task asked for; worker.md declined it,"
            " and the run ends on that") in not_done_of(lines)


def test_a_done_run_has_no_not_done_line_and_every_stop_scores_the_point():
    from agentweft.bench import ladder

    done = summary.build("demo-1", "demo", "t", [summary.a_pass(
        "worker.md", "worker", 1.0, handoff.parse(WORKER), [], False, "ok",
        "")], {"git": False}, [], "")
    assert not [l for l in not_done_of(done) if l.startswith("- not done:")]
    needs = park.lines("worker.md", None, [("worker.md", 2)], ["worker.md"],
                       "python run.py demo --resume demo-1", why="boom",
                       cause=stops.EXCEPTION)
    text = "\n".join(stopped_build({"cause": stops.EXCEPTION, "why": "boom",
                                    "at": "worker.md"}, needs))
    point = [p for p in ladder.score(text)["points"]
             if p["point"] == "not_done"][0]
    assert point["got"] == 1, point["line"]


TRIED = ("HANDOFF\nDID:\n- calc.py: add returns a + b\nTRIED:\n"
         "- a fix in the caller - dropped: two callers would need it\n"
         "END HANDOFF\n")


def why_of(lines):
    view = lines[:lines.index("## full record")]
    return view[view.index("## why"):view.index("## not done")]


def decision_of(lines):
    view = lines[:lines.index("## full record")]
    return view[view.index("## the one decision"):view.index("## why")]


def a_stop(cause, command="python run.py demo --resume demo-1"):
    needs = park.lines("worker.md", None, [("worker.md", 2)], ["worker.md"],
                       command, why="it stopped", cause=cause)
    return stopped_build({"cause": cause, "why": "it stopped",
                          "at": "worker.md"}, needs)


def test_a_stop_whose_cause_says_what_to_do_recommends_it():
    capped = decision_of(a_stop(stops.BUDGET, "python run.py demo --resume"
                                " demo-1 --max-calls <n>"))
    assert ("  recommendation: raise the cap and carry on: python run.py demo"
            " --resume demo-1 --max-calls <n>") in capped
    assert ("  recommendation: carry on as it is once the limit resets;"
            " nothing in the run needs changing: python run.py demo --resume"
            " demo-1") in decision_of(a_stop(stops.OUTAGE))
    assert ("  recommendation: carry on as it is; worker.md runs again:"
            " python run.py demo --resume demo-1") in decision_of(
                a_stop(stops.INTERRUPT))


def test_a_stop_whose_fix_depends_on_its_why_recommends_nothing_and_scores():
    from agentweft.bench import ladder

    lines = a_stop(stops.GATE)
    assert not [l for l in decision_of(lines) if "recommendation" in l]
    point = [p for p in ladder.score("\n".join(lines))["points"]
             if p["point"] == "decision"][0]
    assert point["got"] == 1, point["line"]


def test_what_was_tried_and_dropped_sits_in_the_why_and_still_carries():
    lines = summary.build("demo-1", "demo", "t", [summary.a_pass(
        "patcher.md", "patcher", 1.0, handoff.parse(TRIED), [], False, "ok",
        "")] * 2, {"git": False}, [], "",
        found="RULED OUT:\n- reader.py - it never sees the value\n")
    why = why_of(lines)
    assert why[why.index("tried and dropped, and why:") + 1:][:2] == [
        "- patcher: a fix in the caller - dropped: two callers would need it",
        "- investigator.md ruled out: reader.py - it never sees the value"]
    assert ("- tried and dropped: patcher: a fix in the caller - dropped: two"
            " callers would need it") in lines
    from agentweft.bench import ladder

    point = [p for p in ladder.score("\n".join(lines))["points"]
             if p["point"] == "why"][0]
    assert point["got"] == 1, point["line"]


def test_the_journal_line_points_at_the_handoff():
    now = datetime.datetime(2026, 1, 2, 3, 4)
    ok = stops.line(now, "demo", "ok", 4, "demo-1", saved="d-1.md",
                    spend="1 call", handoff="demo-1/handoff.md")
    assert ok.endswith("  demo-1/handoff.md")
    got = stops.read(ok)
    assert (got.run, got.saved, got.spend, got.handoff) == \
        ("demo-1", "d-1.md", "1 call", "demo-1/handoff.md")
    stop = stops.line(now, "demo", stops.status("parked", "w.md"), 4,
                      "demo-1", cause="parked", spend="1 call",
                      why="waiting for user", handoff="demo-1/handoff.md")
    got = stops.read(stop)
    assert (got.cause, got.why, got.handoff) == \
        ("parked", "waiting for user", "demo-1/handoff.md")
    assert stops.read(stops.line(now, "demo", "ok", 4, "demo-1",
                                 saved="d-1.md")).handoff is None


def test_the_taught_block_says_a_read_or_search_call_backs_a_verified_line():
    composed = resolver.fragment("handoff")
    rules = " ".join(composed.split())
    assert ("a VERIFIED line needs a command you ran in this step, or a"
            " Read, Grep or Glob call you made in it,") in rules
    taught = composed.split("VERIFIED:", 1)[1].split("NOT VERIFIED:", 1)[0]
    assert "Read <file>" in taught and 'Grep "<pattern>" <path>' in taught
    assert handoff.by_tool("Read TASK.md", "Read\t/w/place/TASK.md")
    assert handoff.by_tool('Grep "def mul" calc.py', "Grep\tdef mul\tcalc.py")
