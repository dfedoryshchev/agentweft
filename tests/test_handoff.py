"""every step hands over what it did, what it checked and what it doubts.

the block at the end of a step's answer is parsed onto its steps.jsonl line,
handed to the next step first, and folded into the run's handoff.md, which is
written on every end: finished, parked, gate failed, budget, crash.
"""
import datetime
import json
import subprocess
import sys

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


def test_a_missing_block_is_said_so_to_the_next_step():
    assert "handed over no HANDOFF block" in Handoff("worker", "x\n").as_prompt()


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
