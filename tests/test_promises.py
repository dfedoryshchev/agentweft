import sys

sys.path.insert(0, ".")
from agentweft.guardrails import promises

DIGEST = '''## what changed
- notes.md | changed | moved
- plan.md | changed | rewritten

## needs me
- budget.md | needs-me | sign by friday

## can wait
- old.md | can-wait | nothing
'''


def test_a_clean_digest_breaks_nothing():
    invs = ["no file appears in two lists", "every line names a file"]
    assert promises.failures(DIGEST, invs) == []


def test_a_file_in_two_lists_is_caught():
    bad = DIGEST + "\n## can wait\n- notes.md | can-wait | also here\n"
    out = promises.failures(bad, ["no file appears in two lists"])
    assert out and "notes.md" in out[0][1]


def test_a_line_with_no_filename_is_caught():
    bad = DIGEST + "- something vague\n"
    assert promises.failures(bad, ["every line names a file"])


def test_an_uncheckable_invariant_says_so_rather_than_passing():
    got = promises.check(DIGEST, ["the tone is appropriate"])
    assert got[0][1] is None
    assert "not checkable" in got[0][2]


def test_the_uncheckable_ones_are_listed_apart_from_the_broken_ones():
    invs = ["the tone is appropriate", "every line names a file"]
    assert promises.unchecked(DIGEST, invs) == ["the tone is appropriate"]
    assert promises.failures(DIGEST, invs) == []


def a_finished_run(tmp_path, monkeypatch, invariants):
    """a one-step flow on disk that journals, answered by the fake provider."""
    from agentweft.runner import engine, prompts

    flow = tmp_path / "flows" / "promised"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("# worker\n\ndo the thing.\n",
                                    encoding="utf-8")
    (flow / "instructions.md").write_text("one step, and it answers.\n",
                                          encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: promised\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "promises:\n"
        "  invariants:\n"
        + "".join("    - " + inv + "\n" for inv in invariants)
        + "timeout: 120\n"
        "provider:\n"
        "  provider: fake\n"
        '  reply: "VERDICT: ok\\n\\n- notes.md | changed | moved\\n"\n',
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", "promised", "--force",
                                      "--flows", "flows"])
    engine.main()
    return (tmp_path / "runs" / "journal.md").read_text(encoding="utf-8")


def test_a_run_whose_promises_cannot_be_checked_does_not_journal_a_bare_ok(
        tmp_path, monkeypatch):
    """a clean journal line for a run nothing could check read exactly like a
    run that was checked and held."""
    line = a_finished_run(tmp_path, monkeypatch,
                          ["the tone is appropriate", "nothing is invented"])
    assert "2 promise(s) not checked" in line


def test_a_run_whose_promises_were_all_checked_says_nothing_extra(
        tmp_path, monkeypatch):
    line = a_finished_run(tmp_path, monkeypatch, ["every line names a file"])
    assert "not checked" not in line
    assert "  ok  " in line
