"""the retro's doc, rules and guard changes land in the tree, unstaged, or as
one `retro:` commit after the task's under `commits: wip` or `squash`, each
held to the code as the run left it before the runner writes it."""
import hashlib
import json
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard, fence, snapshot
from agentweft.runner import engine, prompts, resume, retro, state, stops
from test_commit_modes import (CASES, COUNT, COUNT_SAID, COUNTED, TESTER,
                               WORKER, WORKER_SAID, a_place, git, head)
from test_red_order import a_flow as a_repo_flow
from test_retro_maintains import CODE, asked, block, clean, put
from test_stops import the_folder

NL = chr(10)
README = ("# pkg" + NL + NL + "parse returns a list of words." + NL + NL
          + "run it with --words." + NL)
CHANGES = "## the retro's changes (unstaged, yours to stage)"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def edit(file, now, after, because="the run found the raise undocumented"):
    return NL.join(["edit: " + file, "  now: " + now, "  after: " + after,
                    "  because: " + because])


def guard(where, *code):
    return NL.join(["guard: seq 1", "  kind: test", "  where: " + where,
                    "  what: an empty line raises ValueError"]
                   + ["  code: " + line for line in code])


PASSES = ("import pytest", "from pkg.a import parse", "",
          "def test_an_empty_line_raises():",
          "    with pytest.raises(ValueError):", "        parse('')")
FAILS = ("from pkg.a import parse", "", "def test_an_empty_line_is_empty():",
         "    assert parse('') == []")


def handoff():
    return (the_folder() / "handoff.md").read_text(encoding="utf-8")


def changes_of(note):
    assert CHANGES in note, note
    part = note.split(CHANGES)[1]
    return [l for l in part.split("\n## ")[0].split(NL) if l.startswith("- ")]


def test_an_edit_whose_now_is_in_the_readme_rewrites_it_unstaged(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(edit(
        "README.md", "parse returns a list of words.",
        "`parse` returns a list of words and raises on an empty line.")))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README \
        .replace("parse returns a list of words.",
                 "`parse` returns a list of words and raises on an empty"
                 " line.")
    assert changes_of(handoff()) == [
        "- README.md: the run found the raise undocumented"]
    last = json.loads((the_folder() / "steps.jsonl").read_text(
        encoding="utf-8").strip().split(NL)[-1])
    assert last["facts"]["applied"] == [
        {"path": "README.md", "kind": "doc",
         "because": "the run found the raise undocumented"}]
    account = json.loads((the_folder() / "facts.json").read_text(
        encoding="utf-8"))
    assert [(a["path"], a["kind"]) for a in account["applied"]] == [
        ("README.md", "doc")]
    assert "won facts 0, docs 1, guards 0 (0 refused)" in handoff()


def test_an_edit_whose_now_is_not_in_the_file_is_a_proposal_line(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(edit(
        "README.md", "parse returns a dict", "`parse` returns a list")))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    note = handoff()
    assert changes_of(note) == [
        "- facts/PROPOSED.md: what failed a check, kept for you"]
    assert ('- refused a doc change to README.md: "parse returns a dict" is'
            ' not in README.md') in note
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert "## edit README.md" in proposed
    assert 'refused: "parse returns a dict" is not in README.md' in proposed


def test_an_edit_whose_after_quotes_a_flag_not_in_the_tree_is_refused(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    put(tmp_path, "docs/old.md", "run it with --tokens." + NL)
    clean(tmp_path, monkeypatch, fake_cli, block(
        edit("README.md", "run it with --words.", "run it with --tokens."),
        edit("README.md", "parse returns a list of words.",
             "parse returns a list: `return line.split(',')`.")))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    note = handoff()
    assert ("- refused a doc change to README.md: the after quotes --tokens,"
            " which is not in the code as left (a doc does not count) or a"
            " command of this run" in note)
    assert ("the after quotes return line.split(','), which is not in the"
            " code as left") in note


def test_an_edit_to_claude_md_is_applied_and_flagged_first(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    put(tmp_path, "CLAUDE.md", "# notes" + NL + NL + "parse is in a.py." + NL)
    clean(tmp_path, monkeypatch, fake_cli, block(
        edit("README.md", "parse returns a list of words.",
             "`parse` raises on an empty line."),
        edit("CLAUDE.md", "parse is in a.py.", "parse is in pkg/a.py.",
             "the run read pkg/a.py, not a.py")))
    assert engine.main() == 0
    assert "parse is in pkg/a.py." in (tmp_path / "CLAUDE.md").read_text(
        encoding="utf-8")
    assert changes_of(handoff()) == [
        "- CLAUDE.md (instruction file touched): the run read pkg/a.py,"
        " not a.py",
        "- README.md: the run found the raise undocumented"]


def test_a_guard_that_fails_on_the_tree_is_not_written(
        tmp_path, monkeypatch, fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(guard(
        "tests/test_a_guard.py", *FAILS)))
    assert engine.main() == 0
    assert not (tmp_path / "tests" / "test_a_guard.py").exists()
    note = handoff()
    assert ("- refused a guard for seq 1: it does not pass on the tree as"
            " left: tests/test_a_guard.py::test_an_empty_line_is_empty"
            " FAILED") in note
    assert "refused: it does not pass" in (
        tmp_path / "facts" / "PROPOSED.md").read_text(encoding="utf-8")


def test_a_guard_that_passes_is_written_unstaged(tmp_path, monkeypatch,
                                                 fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(guard(
        "tests/test_a_guard.py", *PASSES)))
    assert engine.main() == 0
    written = (tmp_path / "tests" / "test_a_guard.py").read_text(
        encoding="utf-8")
    assert written == NL.join(PASSES) + NL
    assert changes_of(handoff()) == [
        "- tests/test_a_guard.py: guard for seq 1, passes on the tree as"
        " left: an empty line raises ValueError"]
    assert "won facts 0, docs 0, guards 1 (0 refused)" in handoff()


def test_a_gate_guard_stays_a_line_for_a_person(tmp_path, monkeypatch,
                                                fake_cli):
    clean(tmp_path, monkeypatch, fake_cli, block(NL.join([
        "guard: seq 1", "  kind: gate", "  where: flow.yaml worker gates",
        "  what: a red-test gate on pkg/a.py"])))
    assert engine.main() == 0
    note = handoff()
    assert CHANGES not in note
    assert ("- guard (gate, flow.yaml worker gates): a red-test gate on"
            " pkg/a.py (proposed: a gate guard is the flow's to change)"
            in note)
    assert not (tmp_path / "facts" / "PROPOSED.md").exists()


def test_the_retros_inputs_name_a_doc_that_names_a_changed_file(
        tmp_path, monkeypatch):
    place = a_place(tmp_path / "repo")
    (place / "README.md").write_text("# report" + NL + NL + "report.py sorts"
                                     " the names." + NL, encoding="utf-8")
    (place / "NOTES.md").write_text("nothing here." + NL, encoding="utf-8")
    git(place, "add", ".")
    git(place, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
        "docs")
    seen = {}
    code = run_build(tmp_path, monkeypatch, place,
                     TESTER + WORKER + "retro: true" + NL,
                     dict(CASES["red first, then the fix"][1]), seen)
    assert code == stops.EXIT_OK
    prompt = seen["retro.md"]
    part = prompt.split("docs that name a file or a name this run changed,"
                        " each to confirm current or edit:" + NL)[1]
    part = part.split(NL + NL)[0]
    assert part.split(NL) == [
        "- README.md names report.py:",
        "  README.md:3: report.py sorts the names."]
    assert "doc edits and guards this run may make:\n- 3\n" in prompt


def run_build(tmp_path, monkeypatch, place, steps, does, seen=None, *args):
    """main() over a flow `build` in `place`; `does` answers each step as
    (files it writes, what it says), the retro's answer under retro.md."""
    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if seen is not None:
            seen[step] = prompt
        writes, said = does.get(step, ({}, "## change first\n- none\n"))
        for rel, text in writes.items():
            (place / rel).parent.mkdir(parents=True, exist_ok=True)
            (place / rel).write_text(text, encoding="utf-8")
        return said, False

    if not (tmp_path / "flows" / "build").is_dir():
        a_repo_flow(tmp_path, "build", steps)
    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place)] + list(args))
    return engine.main()


def folders():
    return sorted((p for p in state.RUNS.iterdir() if p.is_dir()),
                  key=lambda p: resume.order_of(p.name))


GUARD_REPORT = NL.join([
    "guard: seq 1", "  kind: test", "  where: tests/test_order_guard.py",
    "  what: report sorts the names",
    "  code: from report import report", "  code: ",
    "  code: def test_sorted():",
    "  code:     assert report(['b', 'a']) == ['a', 'b']"])
DOC_REPORT = NL.join([
    "edit: README.md", "  now: report.py sorts the names.",
    "  after: `report` in report.py sorts the names.",
    "  because: the run read report.py"])


def a_documented_place(tmp_path):
    place = a_place(tmp_path / "repo")
    (place / "README.md").write_text("# report" + NL + NL + "report.py sorts"
                                     " the names." + NL, encoding="utf-8")
    git(place, "add", ".")
    git(place, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm",
        "docs")
    return place


def test_under_wip_the_retros_changes_are_one_retro_commit_after_the_tasks(
        tmp_path, monkeypatch):
    place = a_documented_place(tmp_path)
    start = head(place)
    steps = TESTER + WORKER + "commits: wip" + NL + "retro: true" + NL
    does = dict(CASES["red first, then the fix"][1])
    does["retro.md"] = ({}, block(DOC_REPORT, GUARD_REPORT))
    assert run_build(tmp_path, monkeypatch, place, steps, does) \
        == stops.EXIT_OK
    subjects = git(place, "log", "--reverse", "--format=%s",
                   start + "..HEAD").splitlines()
    assert subjects == ["wip(build): tester.md", "wip(build): worker.md",
                        "retro: kept README.md and tests/test_order_guard.py"
                        " current"]
    last = git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               "HEAD").split()
    assert sorted(last) == ["README.md", "tests/test_order_guard.py"]
    assert git(place, "status", "--porcelain") == ""
    note = (folders()[-1] / "handoff.md").read_text(encoding="utf-8")
    assert ("## the retro's changes (in their own commit, yours to review)"
            in note)
    assert "- " + head(place)[:12] + " retro: kept README.md" in note


def test_a_resumed_leg_leaves_the_retros_files_out_of_its_step_commits(
        tmp_path, monkeypatch):
    place = a_documented_place(tmp_path)
    start = head(place)
    steps = TESTER + WORKER + "commits: wip" + NL + "retro: true" + NL
    code = run_build(tmp_path, monkeypatch, place, steps, {
        "tester.md": ({"tests/test_count.py": COUNT}, COUNT_SAID),
        "worker.md": ({}, ""),
        "retro.md": ({}, block(DOC_REPORT, GUARD_REPORT))})
    assert code != stops.EXIT_OK
    first = folders()[-1]
    note = (first / "handoff.md").read_text(encoding="utf-8")
    assert CHANGES in note
    assert "- not committed: the run stopped before every step passed" in note
    assert (place / "tests" / "test_order_guard.py").is_file()
    code = run_build(tmp_path, monkeypatch, place, steps, {
        "worker.md": ({"report.py": COUNTED}, WORKER_SAID)},
        None, "--resume", first.name)
    assert code == stops.EXIT_OK
    assert git(place, "log", "-1", "--format=%s").strip() \
        == "wip(build): worker.md"
    assert git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               "HEAD").split() == ["report.py"]
    left = git(place, "status", "--porcelain")
    assert " M README.md" in left and "?? tests/test_order_guard.py" in left
    assert git(place, "rev-list", "--count", start + "..HEAD").strip() == "2"


def test_the_start_snapshot_takes_the_runners_writes_as_no_change(tmp_path):
    place = a_documented_place(tmp_path)
    shot = snapshot.take(place)
    (place / "README.md").write_text("# report, edited by the runner" + NL,
                                     encoding="utf-8")
    (place / "tests" / "test_order_guard.py").write_text(
        "def test_x():" + NL + "    assert True" + NL, encoding="utf-8")
    assert shot.product_changed() == ["README.md"]
    assert [r for r, _ in shot.test_changes()] == ["tests/test_order_guard.py"]
    applied = {rel: sha((place / rel).read_bytes())
               for rel in ("README.md", "tests/test_order_guard.py")}
    shot.kept_out(applied)
    assert shot.product_changed() == []
    assert shot.test_changes() == []
    assert shot.new_test_ids() == []
    (place / "README.md").write_text("# report, then a step" + NL,
                                     encoding="utf-8")
    assert shot.product_changed() == ["README.md"]


def test_the_fence_takes_a_guard_the_runner_wrote_as_the_runs_own(tmp_path):
    place = a_documented_place(tmp_path)
    (place / "tests" / "test_order_guard.py").write_text(
        "def test_x():" + NL + "    assert True" + NL, encoding="utf-8")
    held = fence.Fence(place)
    (place / "tests" / "test_order_guard.py").write_text(
        "def test_x():" + NL + "    assert 1" + NL, encoding="utf-8")
    assert held.crossed() == [("tests/test_order_guard.py", "changed")]
    held = fence.Fence(place)
    held.kept_out(["tests/test_order_guard.py"])
    (place / "tests" / "test_order_guard.py").unlink()
    assert held.crossed() == []


def test_the_account_lists_the_runners_writes_for_the_legs_after(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "README.md", README)
    store = factsguard.Store(tmp_path)
    store.keep_in(tmp_path / "runs" / "leg-1")
    done = retro.Maintained()
    retro.execute(store, factsguard.Record(tmp_path), [
        ("edit", "README.md", {"scope": [], "now": "run it with --words.",
                               "after": "run it with `parse`.",
                               "because": "the flag is gone"})], done, "r")
    assert done.refused == []
    found = factsguard.applied_in([tmp_path / "runs" / "leg-1"])
    assert found == {"README.md": sha(
        (tmp_path / "README.md").read_bytes())}


def test_an_old_doc_item_reads_as_an_edit():
    from agentweft.runner import upkeep

    items, why = upkeep.parse(block(NL.join([
        "doc: README.md", "  now: a", "  after: b", "  because: c"])))
    assert why == "" and items[0][0] == "doc"
    items, why = upkeep.parse(block(guard("tests/test_g.py", "def test_g():",
                                          "    assert True")))
    assert items[0][2]["code"] == ["def test_g():", "    assert True"]


def test_edits_per_run_is_a_count_and_caps_the_edits(tmp_path):
    from agentweft.flow import spec

    base = {"name": "f", "steps": [{"role": "worker"}]}
    assert spec.check(dict(base, edits_per_run=1)) == []
    assert spec.check(dict(base, edits_per_run="lots")) == [
        "edits_per_run should be a whole number, 0 or more"]
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "README.md", README)
    store = factsguard.Store(tmp_path)
    done = retro.Maintained()
    from agentweft.guardrails import retroedits

    keep = retroedits.Keeper(tmp_path, cap=1)
    retro.execute(store, factsguard.Record(tmp_path), [
        ("edit", "README.md", {"now": "# pkg", "after": "# the pkg",
                               "because": "a"}),
        ("edit", "README.md", {"now": "--words", "after": "`parse`",
                               "because": "b"})], done, "r", keep=keep)
    assert [a["path"] for a in done.applied] == ["README.md"]
    assert done.refused == [("doc change to README.md",
                             "per-run cap: 1 doc edits and guards are"
                             " already made this run")]


def test_an_edit_is_refused_on_a_spec_a_test_a_secret_and_the_store(
        tmp_path):
    from agentweft.guardrails import retroedits

    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "TASK.md", "parse raises." + NL)
    put(tmp_path, "tests/test_a.py", "def test_a():" + NL + "    pass" + NL)
    put(tmp_path, ".env.md", "KEY=1" + NL)
    put(tmp_path, "facts/INDEX.md", "# facts" + NL)
    tree = retroedits.Tree(tmp_path)
    record = factsguard.Record(tmp_path)
    said = dict((rel, retroedits.edit_refusal(
        tmp_path, rel, {"now": "x", "after": "y", "because": "z"}, record,
        tree)[0]) for rel in ("TASK.md", "tests/test_a.py", ".env.md",
                              "facts/INDEX.md", "../out.md", "pkg/a.py"))
    assert said["TASK.md"].startswith("TASK.md is a spec file")
    assert said["tests/test_a.py"].startswith("tests/test_a.py is a test")
    assert said[".env.md"].startswith("it looks like a secret")
    assert said["facts/INDEX.md"].startswith("facts/INDEX.md is under facts/")
    assert said["../out.md"] == "../out.md is outside the place"
    assert said["pkg/a.py"].startswith("pkg/a.py is not a doc")
