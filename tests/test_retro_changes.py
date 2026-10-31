"""the retro's changes are the store's files alone: unstaged, or one `retro:`
commit after the task's under `commits: wip` or `squash`. a doc edit or a
test guard it still asks for is kept as a nice-to-do ticket on its one file,
or refused with why into facts/PROPOSED.md; no other file of the tree is
written for it."""
import hashlib
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft.guardrails import factsguard, fence, snapshot
from agentweft.runner import engine, prompts, resume, retro, state, stops, \
    upkeep
from test_commit_modes import (CASES, COUNT, COUNT_SAID, COUNTED, TESTER,
                               WORKER, WORKER_SAID, a_place, git, head)
from test_red_order import a_flow as a_repo_flow
from test_retro_maintains import CODE, block, clean, put
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


def handoff():
    return (the_folder() / "handoff.md").read_text(encoding="utf-8")


def changes_of(note):
    assert CHANGES in note, note
    part = note.split(CHANGES)[1]
    return [l for l in part.split("\n## ")[0].split(NL) if l.startswith("- ")]


def test_an_edit_kept_as_a_ticket_lists_only_the_store_as_changed(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(edit(
        "README.md", "parse returns a list of words.",
        "`parse` returns a list of words and raises on an empty line.")))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    changed = changes_of(handoff())
    assert changed and all(l.startswith("- facts/") for l in changed), changed
    last = json.loads((the_folder() / "steps.jsonl").read_text(
        encoding="utf-8").strip().split(NL)[-1])
    assert "applied" not in last["facts"]
    assert "applied" not in json.loads((the_folder() / "facts.json")
                                       .read_text(encoding="utf-8"))
    assert "won facts 0, tickets 1 (0 refused)" in handoff()


def test_an_edit_whose_now_is_not_in_the_file_is_a_proposal_line(
        tmp_path, monkeypatch, fake_cli):
    put(tmp_path, "README.md", README)
    clean(tmp_path, monkeypatch, fake_cli, block(edit(
        "README.md", "parse returns a dict", "`parse` returns a list")))
    assert engine.main() == 0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    note = handoff()
    assert changes_of(note) == [
        "- facts/PROPOSED.md: what could not be kept, kept for you"]
    why = upkeep.NO_WRITE + '"parse returns a dict" is not in README.md'
    assert "- refused a doc change to README.md: " + why in note
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert "## edit README.md" in proposed
    assert "refused: " + why in proposed


def test_an_edit_to_claude_md_is_a_ticket_and_the_file_stays_as_written(
        tmp_path, monkeypatch, fake_cli):
    notes = "# notes" + NL + NL + "parse is in a.py." + NL
    put(tmp_path, "CLAUDE.md", notes)
    clean(tmp_path, monkeypatch, fake_cli, block(
        edit("CLAUDE.md", "parse is in a.py.", "parse is in pkg/a.py.",
             "the run read pkg/a.py, not a.py")))
    assert engine.main() == 0
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == notes
    [fact] = factsguard.Store(tmp_path).read()
    assert (fact.kind, fact.scopes) == ("nice-to-do", ["CLAUDE.md"])


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


def defect(seq="seq 1 worker.md"):
    return NL.join(["fact:", "  scope: pkg/a.py", "  kind: defect",
                    "  claim: an empty line raises where the spec says it"
                    " is skipped",
                    "  why: the run left it, the spec asks for a skip",
                    "  source: " + seq + '; evidence: pkg/a.py:5 "raise'
                    ' ValueError"'])


def named_guard(head, where="tests/test_a_guard.py"):
    return guard(where, *PASSES).replace("guard: seq 1", "guard: " + head, 1)


PINS = ("it guards a defect the run left in place ({}): a test that passes on"
        " the tree as left holds the defect, not its fix")


@pytest.mark.parametrize("head", ["seq 1 worker.md", "seq 1", "seq 1 worker",
                                  "seq 01 worker.md", "Seq 1 Worker.md"])
def test_a_guard_for_a_defect_the_block_files_is_a_proposal_never_a_test(
        tmp_path, monkeypatch, fake_cli, head):
    clean(tmp_path, monkeypatch, fake_cli, block(defect(), named_guard(head)))
    assert engine.main() == 0
    assert not (tmp_path / "tests" / "test_a_guard.py").exists()
    why = PINS.format("the defect fact from seq 1 worker.md")
    assert "- refused a guard for " + head + ": " + why in handoff()
    proposed = (tmp_path / "facts" / "PROPOSED.md").read_text(
        encoding="utf-8")
    assert "refused: " + why in proposed
    assert "code:" in proposed
    assert [f.kind for f in factsguard.Store(tmp_path).read()] == ["defect"]


@pytest.mark.parametrize("head", ["F-0001", "F-1", "f-0001"])
def test_a_guard_for_a_defect_on_record_is_a_proposal_never_a_test(
        tmp_path, monkeypatch, fake_cli, head):
    put(tmp_path, "facts/pkg/a.py.md",
        "## F-0001 live\nscope: pkg/a.py\nkind: defect\nclaim: an empty line"
        " raises\nwhy: the spec asks for a skip\n")
    clean(tmp_path, monkeypatch, fake_cli, block(named_guard(head)))
    assert engine.main() == 0
    assert not (tmp_path / "tests" / "test_a_guard.py").exists()
    assert ("- refused a guard for " + head + ": "
            + PINS.format("F-0001, a defect on record")) in handoff()


@pytest.mark.parametrize("seq, head", [("seq 2 tester.md", "seq 1"),
                                       ("seq 1 tester.md", "seq 1 worker.md")])
def test_a_guard_for_another_step_than_the_defect_is_held_as_a_ticket(
        tmp_path, monkeypatch, fake_cli, seq, head):
    clean(tmp_path, monkeypatch, fake_cli, block(defect(seq),
                                                 named_guard(head)))
    assert engine.main() == 0
    note = handoff()
    assert "it guards a defect the run left in place" not in note
    assert "- refused a guard for " + head + ": " + upkeep.NO_WRITE in note
    assert not (tmp_path / "tests" / "test_a_guard.py").exists()


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
                        " each to confirm current or keep a ticket on:"
                        + NL)[1]
    part = part.split(NL + NL)[0]
    assert part.split(NL) == [
        "- README.md names report.py:",
        "  README.md:3: report.py sorts the names."]
    assert "nice-to-do tickets this run may write:\n- 3\n" in prompt


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
    readme = (place / "README.md").read_text(encoding="utf-8")
    steps = TESTER + WORKER + "commits: wip" + NL + "retro: true" + NL
    does = dict(CASES["red first, then the fix"][1])
    does["retro.md"] = ({}, block(DOC_REPORT, GUARD_REPORT))
    assert run_build(tmp_path, monkeypatch, place, steps, does) \
        == stops.EXIT_OK
    subjects = git(place, "log", "--reverse", "--format=%s",
                   start + "..HEAD").splitlines()
    assert subjects == ["wip(build): tester.md", "wip(build): worker.md",
                        "retro: kept 1 fact current"]
    last = git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               "HEAD").split()
    assert "facts/README.md.md" in last
    assert all(rel.startswith("facts/") for rel in last), last
    assert (place / "README.md").read_text(encoding="utf-8") == readme
    assert not (place / "tests" / "test_order_guard.py").exists()
    assert git(place, "status", "--porcelain") == ""
    note = (folders()[-1] / "handoff.md").read_text(encoding="utf-8")
    assert ("## the retro's changes (in their own commit, yours to review)"
            in note)
    assert "- " + head(place)[:12] + " retro: kept 1 fact current" in note


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
    assert (place / "facts" / "README.md.md").is_file()
    code = run_build(tmp_path, monkeypatch, place, steps, {
        "worker.md": ({"report.py": COUNTED}, WORKER_SAID)},
        None, "--resume", first.name)
    assert code == stops.EXIT_OK
    assert git(place, "log", "-1", "--format=%s").strip() \
        == "wip(build): worker.md"
    assert git(place, "diff-tree", "--no-commit-id", "--name-only", "-r",
               "HEAD").split() == ["report.py"]
    left = git(place, "status", "--porcelain")
    assert "?? facts/" in left and "README.md" not in left
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
    held.kept_out({"tests/test_order_guard.py": sha(
        (place / "tests" / "test_order_guard.py").read_bytes())})
    (place / "tests" / "test_order_guard.py").unlink()
    assert held.crossed() == []


def test_the_account_lists_no_write_outside_the_store_for_the_legs_after(
        tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    put(tmp_path, "README.md", README)
    store = factsguard.Store(tmp_path)
    store.keep_in(tmp_path / "runs" / "leg-1")
    done = retro.Maintained()
    retro.execute(store, factsguard.Record(tmp_path), [
        ("edit", "README.md", {"scope": [], "now": "run it with --words.",
                               "after": "run it with `parse`.",
                               "because": "the flag is gone"})], done, "r")
    assert done.refused == [] and len(done.tickets) == 1
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == README
    assert factsguard.applied_in([tmp_path / "runs" / "leg-1"]) == {}


def test_an_old_doc_item_reads_as_an_edit():
    items, why = upkeep.parse(block(NL.join([
        "doc: README.md", "  now: a", "  after: b", "  because: c"])))
    assert why == "" and items[0][0] == "doc"
    items, why = upkeep.parse(block(guard("tests/test_g.py", "def test_g():",
                                          "    assert True")))
    assert items[0][2]["code"] == ["def test_g():", "    assert True"]


def test_tickets_per_run_is_a_count_the_store_takes():
    from agentweft.flow import spec

    base = {"name": "f", "steps": [{"role": "worker"}]}
    assert spec.check(dict(base, tickets_per_run=1)) == []
    assert spec.check(dict(base, tickets_per_run="lots")) == [
        "tickets_per_run should be a whole number, 0 or more"]
    assert spec.check(dict(base, edits_per_run=1)) != []
    assert factsguard.tickets_of({"tickets_per_run": 1}) == 1
    assert factsguard.tickets_of({}) == factsguard.TICKETS


def kept_as(tmp_path, rel, now="x", after="y"):
    """-> why an edit of `rel` is not kept as a ticket, "" when it is."""
    store = factsguard.Store(tmp_path)
    done = retro.Maintained()
    retro.execute(store, factsguard.Record(tmp_path), [
        ("edit", rel, {"scope": [], "now": now, "after": after,
                       "because": "z"})], done, "r")
    return done.refused[0][1] if done.refused else ""


def test_an_edit_is_no_ticket_on_a_spec_a_secret_the_store_or_outside(
        tmp_path):
    put(tmp_path, "pkg/a.py", "x = 1" + NL)
    put(tmp_path, "TASK.md", "x is one." + NL)
    put(tmp_path, "tests/test_a.py", "x = 1" + NL)
    put(tmp_path, ".env.md", "x KEY=1" + NL)
    put(tmp_path, "facts/INDEX.md", "# facts x" + NL)
    said = dict((rel, kept_as(tmp_path, rel)) for rel in (
        "TASK.md", ".env.md", "facts/INDEX.md", "../out.md",
        "tests/test_a.py", "pkg/a.py"))
    assert "TASK.md is a spec file" in said["TASK.md"]
    assert "it looks like a secret" in said[".env.md"]
    assert "facts/INDEX.md is the runner's to write" in said["facts/INDEX.md"]
    assert "names the one file it is done in" in said["../out.md"]
    assert said["tests/test_a.py"] == said["pkg/a.py"] == ""


def test_an_edit_or_a_guard_that_holds_an_absolute_path_is_refused(tmp_path):
    tool, home = "D" + ":\\work\\tool.exe", "/" + "home/me/pkg/a.py"
    put(tmp_path, "README.md", "# pkg" + NL + "run the tool." + NL)
    assert ("it names a path on the machine it ran on (" + tool + ")"
            in kept_as(tmp_path, "README.md", "run the tool.", "run " + tool))
    put(tmp_path, "tests/test_g.py", "x = 1" + NL)
    store = factsguard.Store(tmp_path)
    done = retro.Maintained()
    retro.execute(store, factsguard.Record(tmp_path), [
        ("guard", "seq 1", {"scope": [], "kind": "test",
                            "where": "tests/test_g.py",
                            "what": "open('" + home + "') fails",
                            "source": 'evidence: tests/test_g.py:1 "x = 1"'})],
        done, "r")
    [(_, why)] = done.refused
    assert "it names a path on the machine it ran on (" + home + ")" in why


@pytest.mark.parametrize("tracked", [False, True])
def test_a_doc_not_committed_when_the_run_began_is_never_changed(
        tmp_path, monkeypatch, tracked):
    place = a_documented_place(tmp_path)
    notes = "# notes" + NL + NL + "report.py sorts the names." + NL
    if tracked:
        (place / "README.md").write_text(notes, encoding="utf-8")
        rel = "README.md"
    else:
        (place / "NOTES.md").write_text(notes, encoding="utf-8")
        rel = "NOTES.md"
    start = head(place)
    steps = TESTER + WORKER + "commits: wip" + NL + "retro: true" + NL
    does = dict(CASES["red first, then the fix"][1])
    does["retro.md"] = ({}, block(DOC_REPORT.replace("README.md", rel)))
    assert run_build(tmp_path, monkeypatch, place, steps, does) \
        == stops.EXIT_OK
    assert (place / rel).read_text(encoding="utf-8") == notes
    named = git(place, "log", "--format=", "--name-only",
                start + "..HEAD").split()
    assert rel not in named
