import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.guardrails import boundary
from agentweft.roles import resolver
from agentweft.runner import engine, prompts

DIFF = ("here is the change\n"
        "\n"
        "--- a/app/api.py\n"
        "+++ b/app/api.py\n"
        "@@ -1,3 +1,4 @@\n"
        "+import os\n")

SHELL = ("i ran the suite\n"
         "\n"
         "```bash\n"
         "pytest -q\n"
         "```\n")


def test_a_step_that_declared_no_grant_has_no_boundary_to_cross():
    """None is "said nothing"; [] is "said nothing is allowed".

    every flow in the repo is the first case, so getting these the wrong way
    round would flag every step of every run the first time one printed a
    command, which is the shape of a check nobody leaves switched on.
    """
    assert boundary.check("$ rm -rf /\n", None) == []
    assert boundary.check("$ rm -rf /\n", []) != []


def test_every_mark_asks_for_a_tool_the_checker_knows():
    """the marks and the flow checker have to mean the same six words.

    a mark needing a grant no step could ever be given can never be satisfied,
    and it would read as a finding about the step rather than about this file.
    """
    for mark in boundary.MARKS:
        assert mark.needs
        # every mark is a heuristic, so it has to carry the argument against
        # itself into the note. `RESIDUE` is held to the same thing.
        assert mark.why.strip()
        for tool in mark.needs:
            assert tool in spec.GRANTS, tool
    for tool in boundary.UNSEEN:
        assert tool in spec.GRANTS, tool


def test_what_it_cannot_see_is_named_rather_than_passed_over():
    """a grant this cannot check has to say so, the way an unmatched invariant
    does. silence would read as "checked, nothing found"."""
    assert set(boundary.MARKED) | set(boundary.UNSEEN) == set(spec.GRANTS)
    assert all(why.strip() for why in boundary.UNSEEN.values())


def found(text, granted):
    """-> what each finding is about, so a test can say it without unpacking."""
    return [mark.what for mark, _line in boundary.check(text, granted)]


def test_a_shell_is_shown_by_a_fence_or_by_a_prompt():
    """the two ways an answer says it ran something, both of them typed by the
    model rather than observed by anything here."""
    for text in ["```bash\npytest -q\n```\n",
                 "```console\nls\n```\n",
                 "```shell-session\nls\n```\n",
                 "$ pytest -q\n"]:
        assert found(text, []) == ["ran a command"], text


def test_a_changed_file_is_shown_by_the_diff_it_arrives_in():
    """a hunk header, either file header, or a fence saying diff. one of them
    is enough, because a model quoting a diff rarely quotes all of it."""
    for text in ["@@ -1,3 +1,4 @@\n", "--- a/x.py\n", "+++ b/x.py\n",
                 "```diff\n+x = 1\n```\n", "```patch\n+x = 1\n```\n"]:
        assert found(text, []) == ["changed a file"], text


def test_the_step_that_was_granted_it_comes_back_clean():
    """the same text, twice, and only the grant is different. that is the whole
    check: this reads the boundary, not the behaviour."""
    assert found(SHELL, []) == ["ran a command"]
    assert found(SHELL, ["shell"]) == []
    assert found(DIFF, []) == ["changed a file"]
    assert found(DIFF, ["edit"]) == []
    # `write` answers for it too. a diff says a file changed and not whether it
    # was there first, so holding a role granted one and not the other to the
    # difference would be flagging a formatting choice.
    assert found(DIFF, ["write"]) == []


def test_a_step_granted_neither_word_is_caught_by_both_marks():
    assert sorted(found(SHELL + DIFF, [])) == ["changed a file",
                                               "ran a command"]
    assert found(SHELL + DIFF, ["shell", "write"]) == []


def test_saying_it_would_need_a_tool_is_not_using_one():
    """the grant asks a step to name what it needs and stop. a step that does
    exactly that must not then be flagged for saying so, or the instruction
    and the check disagree and the check wins.
    """
    said = ("i would need a shell to run pytest here, and write access to fix\n"
            "the import. naming it and stopping, as asked.\n")
    assert boundary.check(said, []) == []
    # a path and a command name in prose are not a run either
    assert boundary.check("run pytest -q in app/api.py to see it\n", []) == []


def test_reading_and_searching_leave_no_mark_so_nothing_claims_they_do():
    """a step granted nothing at all, quoting a file the way every step does.

    this is the case UNSEEN exists to be honest about: it comes back clean,
    and clean here means unchecked rather than allowed.
    """
    quoted = "app/api.py says:\n\n    def get(self):\n        return 1\n"
    assert boundary.check(quoted, []) == []
    assert "read" in boundary.UNSEEN and "grep" in boundary.UNSEEN


def test_the_false_positive_is_written_down_rather_than_denied():
    """a reviewer granted read and grep is HANDED a diff, and quoting it back
    is flagged. that is wrong about the step and right about the text, and the
    note has to carry enough for whoever reads it to tell which.
    """
    note = boundary.as_note(boundary.check(DIFF, ["read", "grep"]))
    assert "changed a file" in note
    # the first line that matched, so the finding can be argued with. first
    # rather than every one: three lines of the same diff is the same finding
    # said three times, and the file header is where a reader would look.
    assert "--- a/app/api.py" in note
    # and the reason it is a heuristic, in the same breath
    assert "HANDED a diff" in note
    assert note.endswith(chr(10))


def test_nothing_found_is_no_note_at_all():
    """an empty note file beside the gate results would read as a run that was
    checked and had something to say."""
    assert boundary.as_note([]) == ""
    assert boundary.as_note(boundary.check(SHELL, ["shell"])) == ""


def test_the_grant_goes_out_before_the_answer_comes_back():
    """the asking half. a step held to a boundary nobody told it about is a
    trap, and this is the only part of the pair that happens in time to make a
    difference to what comes back.
    """
    asked = boundary.as_prompt(["read", "grep"])
    assert "what you may use: read, grep." in asked
    assert "you do not have write, edit, shell, browser." in asked
    assert "name it and stop" in asked
    # a step that said nothing is asked nothing
    assert boundary.as_prompt(None) == ""
    # and one that may touch nothing is told so in a word rather than a blank
    assert "what you may use: nothing." in boundary.as_prompt([])


def test_a_grant_of_everything_withholds_nothing():
    asked = boundary.as_prompt(list(spec.GRANTS))
    assert "you do not have" not in asked


def a_run(steps):
    """a Run over `steps`, built the way `test_park.py` builds one."""
    fm = runner.config("summarise-and-check")
    by_role = resolver.resolve(fm.raw, runner.flow_path("summarise-and-check"))
    run = runner.Run("summarise-and-check", fm, by_role)
    run.fm = spec.load({"name": "x", "steps": steps})
    return run


def test_a_step_reads_its_grant_off_the_flow_file():
    """and it is keyed the same way `pause_for` and `gates_for` are keyed, off
    the prompt file rather than the role, so a step pointing somewhere else
    still finds its own grant.
    """
    run = a_run([{"role": "worker", "tools": ["read"]},
                 {"role": "reviewer", "prompt": "second-pass.md", "tools": []},
                 {"role": "merge"}])
    assert run.grant_for("worker.md") == ["read"]
    assert run.grant_for("second-pass.md") == []
    # said nothing, and that is not the same answer as said nothing is allowed
    assert run.grant_for("merge.md") is None
    assert run.grant_for("gone.md") is None


def test_the_pair_meets_at_the_step_that_came_back():
    """the check takes what the step produced and what the flow granted it, and
    those two are the only inputs. pinning them together is pinning the seam.
    """
    run = a_run([{"role": "worker", "tools": ["read", "grep"]},
                 {"role": "reviewer"}])
    assert found(SHELL, run.grant_for("worker.md")) == ["ran a command"]
    assert boundary.check(SHELL, run.grant_for("reviewer.md")) == []


def a_flow(tmp_path, reply, tools):
    """a one-step flow on disk, answered by the fake provider.

    the check runs between steps of a real run, so the last two tests drive a
    run rather than the functions above. `journal: false` keeps it out of the
    journal the way the examples do.
    """
    flow = tmp_path / "flows" / "caught"
    flow.mkdir(parents=True)
    (flow / "worker.md").write_text("# worker\n\ndo the thing.\n",
                                    encoding="utf-8")
    (flow / "instructions.md").write_text("one step, and it answers.\n",
                                          encoding="utf-8")
    (flow / "flow.yaml").write_text(
        "name: caught\n"
        "steps:\n"
        "  - role: worker\n"
        "    prompt: worker.md\n"
        "    tools: " + tools + "\n"
        "timeout: 120\n"
        "journal: false\n"
        "provider:\n"
        "  provider: fake\n"
        "  reply: " + repr(reply).replace("'", '"') + "\n",
        encoding="utf-8")
    return flow


def a_finished_run(tmp_path, monkeypatch, reply, tools):
    a_flow(tmp_path, reply, tools)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", "caught", "--force",
                                      "--flows", "flows"])
    engine.main()
    # the run folder, not the digest file saved beside it under a name of the
    # same shape
    return sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]


def test_a_step_is_caught_after_it_answers_and_the_run_carries_on(tmp_path,
                                                                   monkeypatch):
    """the note lands beside the step output, and the step output is there,
    which is the point: nothing was stopped.

    a check that stopped the run would be theatre. whatever it is reporting
    happened wherever the model is, which is not somewhere this runner has a
    seam in.
    """
    where = a_finished_run(tmp_path, monkeypatch,
                           "VERDICT: ok\n\n$ pytest -q\n", "[read, grep]")
    note = (where / "boundary.md").read_text(encoding="utf-8")
    assert "## worker.md" in note
    assert "ran a command" in note
    assert "$ pytest -q" in note
    # the run finished: the step wrote what it produced, and the index carries
    # the ordinary finished line rather than a FAILED or a GATE one
    assert (where / "worker.md").exists()
    index = (tmp_path / "runs" / "index.md").read_text(encoding="utf-8")
    assert index.strip().endswith("caught  1 steps")
    assert "FAILED" not in index and "GATE" not in index


def test_the_same_run_granted_the_shell_writes_no_note(tmp_path, monkeypatch):
    """same flow, same answer, one word different in flow.yaml."""
    where = a_finished_run(tmp_path, monkeypatch,
                           "VERDICT: ok\n\n$ pytest -q\n", "[shell]")
    assert not (where / "boundary.md").exists()
    assert (where / "worker.md").exists()
