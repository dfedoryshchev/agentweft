"""a step that says what it writes is held to it, from content hashes after
the step: tests touch no product code and no spec, product touches no spec,
spec touches nothing but the spec files, none touches nothing."""
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import spec
from agentweft.orchestrate import decisions
from agentweft.runner import engine, prompts, resume, stops

from test_red_order import (BUGGY, FIXED, NL, RED_TEST, TESTER, TESTER_SAID,
                            WORKER, a_flow, a_repo, folders, git, read,
                            running)

ANALYST = ("  - role: analyst" + NL + "    prompt: analyst.md" + NL
           + "    writes: spec" + NL)
REVIEWER = ("  - role: reviewer" + NL + "    prompt: reviewer.md" + NL
            + "    writes: none" + NL)
TASK = "# calc" + NL + NL + "- add adds." + NL
MORE = TASK + "- add takes two numbers." + NL


def a_spec_repo(where):
    place = a_repo(where)
    (place / "TASK.md").write_text(TASK, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "spec")
    return place


def flow_with(tmp_path, name, steps, top=""):
    a_flow(tmp_path, name, steps)
    folder = tmp_path / "flows" / name
    for role in ("analyst", "reviewer"):
        (folder / (role + ".md")).write_text("# " + role + NL + NL + "go."
                                             + NL, encoding="utf-8")
    if top:
        with open(folder / "flow.yaml", "a", encoding="utf-8") as f:
            f.write(top)


def why_of_last_run():
    return read(folders()[-1] / "why.md")


# a breach fails the step, which goes back once and then stops the run


def test_a_tests_step_that_changes_the_spec_fails(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST, "TASK.md": MORE},
                      TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert called == ["tester.md", "tester.md"]
    assert code == stops.exit_code(stops.GATE)
    why = why_of_last_run()
    assert "tester.md writes tests only and changed spec files: TASK.md" \
        in why


def test_a_product_step_that_changes_the_spec_fails(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED, "TASK.md": MORE}, "done")})
    assert called == ["tester.md", "worker.md", "worker.md"]
    assert code == stops.exit_code(stops.GATE)
    assert "worker.md writes product code and changed spec files: TASK.md" \
        in why_of_last_run()


def test_a_product_step_may_change_the_spec_a_ruling_quotes(tmp_path,
                                                            monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    decisions.record(place, "add takes two", '"add takes two numbers." is'
                     " asked for")
    flow_with(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED, "TASK.md": MORE}, "done")})
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK


def test_a_spec_step_that_changes_product_code_fails(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    code, called = running(tmp_path, monkeypatch, place, "plan", {
        "analyst.md": ({"TASK.md": MORE, "calc.py": FIXED}, "done")})
    assert called == ["analyst.md", "analyst.md"]
    assert code == stops.exit_code(stops.GATE)
    assert "analyst.md writes the spec only and changed product code:" \
        " calc.py" in why_of_last_run()


def test_a_spec_step_that_changes_a_test_fails(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    code, called = running(tmp_path, monkeypatch, place, "plan", {
        "analyst.md": ({"tests/test_calc.py": RED_TEST}, "done")})
    assert code == stops.exit_code(stops.GATE)
    assert "analyst.md writes the spec only and changed tests:" \
        " tests/test_calc.py" in why_of_last_run()


def test_a_spec_step_that_commits_product_code_still_fails(tmp_path,
                                                           monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)

    def committing(prompt, timeout=None, cap=3, step="?", provider=None):
        (place / "calc.py").write_text(FIXED, encoding="utf-8")
        subprocess.run(["git", "-C", str(place), "commit", "-qam", "fix"],
                       capture_output=True)
        return "done", False

    code = in_place(tmp_path, monkeypatch, place, "plan", committing)
    assert git(place, "log", "-1", "--format=%s").strip() == "fix"
    assert code == stops.exit_code(stops.GATE)
    assert "changed product code: calc.py" in why_of_last_run()


def test_a_step_that_writes_nothing_and_changes_a_file_fails(tmp_path,
                                                             monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "look", REVIEWER)
    code, called = running(tmp_path, monkeypatch, place, "look", {
        "reviewer.md": ({"calc.py": FIXED}, "VERDICT: ok" + NL)})
    assert called == ["reviewer.md", "reviewer.md"]
    assert code == stops.exit_code(stops.GATE)
    assert "reviewer.md writes nothing and changed product code: calc.py" \
        in why_of_last_run()


def in_place(tmp_path, monkeypatch, place, flow, call):
    monkeypatch.setattr(engine, "call", call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force", "--workdir",
                                      str(place)])
    return engine.main()


# a clean step of each kind passes


def test_a_spec_step_may_change_and_create_spec_files(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    code, called = running(tmp_path, monkeypatch, place, "plan", {
        "analyst.md": ({"TASK.md": MORE, "SPEC-api.md": "# api" + NL,
                        "docs/spec-limits.md": "# limits" + NL}, "done")})
    assert called == ["analyst.md"]
    assert code == stops.EXIT_OK


def test_a_spec_step_sent_back_can_undo_what_it_should_not_have_changed(
        tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    code, called = running(tmp_path, monkeypatch, place, "plan", {
        "analyst.md": [({"TASK.md": MORE, "calc.py": FIXED}, "done"),
                       ({"calc.py": BUGGY}, "done")]})
    assert called == ["analyst.md", "analyst.md"]
    assert code == stops.EXIT_OK


def test_clean_spec_tests_product_and_review_steps_end_done(tmp_path,
                                                           monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "build", ANALYST + TESTER + WORKER + REVIEWER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "analyst.md": ({"TASK.md": MORE}, "done"),
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done"),
        "reviewer.md": ({}, "VERDICT: ok" + NL + NL + "- calc.py: fine" + NL)})
    assert called == ["analyst.md", "tester.md", "worker.md", "reviewer.md"]
    assert code == stops.EXIT_OK


def test_a_product_step_may_add_to_the_spec_when_the_flow_allows_additions(
        tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "build", TESTER + WORKER,
              top="spec_files: additions" + NL)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED, "TASK.md": MORE}, "done")})
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK


def test_skip_tests_still_holds_a_spec_step(tmp_path, monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    code, _ = running(tmp_path, monkeypatch, place, "plan", {
        "analyst.md": ({"calc.py": FIXED}, "done")}, "--skip-tests", "docs")
    assert code == stops.exit_code(stops.GATE)


# the checker


def a_raw(*steps, **top):
    return dict({"name": "x", "steps": list(steps)}, **top)


def test_the_checker_takes_writes_spec():
    assert spec.check(a_raw({"role": "analyst", "writes": "spec"})) == []


def test_the_checker_lists_what_a_step_may_write_without_a_bar():
    bad = spec.check(a_raw({"role": "analyst", "writes": "spec"},
                           {"role": "reviewer"}))
    assert any("tests, product, spec, none" in b for b in bad), bad
    assert not any("|" in b for b in bad), bad


def test_a_spec_step_in_a_flow_whose_spec_is_read_only_is_refused():
    bad = spec.check(a_raw({"role": "analyst", "writes": "spec"},
                           spec_files="read-only"))
    assert any("writes: spec" in b and "read-only" in b for b in bad), bad


# the tools and the prompt


def test_a_spec_step_is_granted_only_the_read_and_edit_tools():
    assert spec.grant_of({"role": "analyst", "writes": "spec"}) == \
        ["read", "grep", "write", "edit"]
    assert spec.grant_of({"role": "analyst", "writes": "spec",
                          "tools": ["read"]}) == ["read"]
    assert spec.grant_of({"role": "worker", "writes": "product"}) is None


def test_a_spec_steps_claude_is_fenced_to_those_tools(tmp_path, monkeypatch):
    flow_with(tmp_path, "plan", ANALYST)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    fm = runner.config("plan")
    run = engine.Run("plan", fm, {"analyst": ""},
                     provider={"provider": "cli", "command": "claude"})
    assert run.by_step["analyst.md"].grant == ["read", "grep", "write",
                                               "edit"]
    assert run.grant_for("analyst.md") == ["read", "grep", "write", "edit"]


def test_a_spec_step_is_told_the_spec_files_one_per_line(tmp_path,
                                                        monkeypatch):
    place = a_spec_repo(tmp_path / "repo")
    flow_with(tmp_path, "plan", ANALYST)
    seen = []

    def call(prompt, timeout=None, cap=3, step="?", provider=None):
        seen.append(prompt)
        return "done", False

    in_place(tmp_path, monkeypatch, place, "plan", call)
    said = seen[0]
    assert NL + "- TASK.md" + NL + "- SPEC*.md" + NL + "- docs/spec*" + NL \
        in said
    assert "changing any other file fails this step" in said


def test_a_reviewer_that_asks_and_is_ruled_by_the_lead_is_not_charged_with_the_ruling(
        tmp_path, monkeypatch):
    import test_lead as ld

    answers = {"planner.md": [ld.PLAN, ld.DECIDED], "tester.md": [ld.TESTER],
               "worker.md": [ld.WORKER], "reviewer.md": [ld.NEEDS, ld.OK],
               "reviewer-runs.md": [ld.OK]}
    writes = {"tester.md": [("tests/test_mul.py", ld.TEST)],
              "worker.md": [("calc.py", ld.AFTER)]}
    asked, _, code, folder, _ = ld.run_it(tmp_path, monkeypatch,
                                          "build-feature", answers, writes)
    why = folder / "why.md"
    assert code == 0, why.read_text(encoding="utf-8") if why.exists() else ""
    assert asked == ["planner.md", "tester.md", "worker.md", "reviewer.md",
                     "planner.md", "reviewer.md", "reviewer-runs.md"]


def test_decisions_md_has_no_name_that_lets_a_step_change_it():
    from agentweft.guardrails import writes

    before = ({}, {}, {decisions.FILE: "a" * 64})
    after = ({}, {}, {decisions.FILE: "b" * 64})
    said = writes.held("tester.md", "tests", before, after, lambda rel: rel)
    assert said.startswith("tester.md writes tests only and changed product"
                           " code: " + decisions.FILE)
