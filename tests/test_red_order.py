"""no product code is written before a red test exists, unless the run says
skip tests. each run here is in a repo whose steps commit nothing."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.flow import spec
from agentweft.guardrails import redorder, snapshot
from agentweft.guardrails.gates.base import Result
from agentweft.runner import engine, prompts, resume, state, stops

NL = chr(10)
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
RED_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == 3" + NL)
TESTER_SAID = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
PYTEST = ["python", "-m", "pytest", "-q", "{test}"]
RED_GATE = ("    gates:" + NL + "      - gate: red-test" + NL
            + "        red: true" + NL
            + "        command: [\"python\", \"-m\", \"pytest\", \"-q\","
            " \"{test}\"]" + NL)
TESTER = ("  - role: tester" + NL + "    prompt: tester.md" + NL
          + "    writes: tests" + NL + RED_GATE)
WORKER = ("  - role: worker" + NL + "    prompt: worker.md" + NL
          + "    writes: product" + NL)


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(
        "def test_old():" + NL + "    assert True" + NL, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def a_flow(tmp_path, name, steps):
    folder = tmp_path / "flows" / name
    folder.mkdir(parents=True)
    (folder / "flow.yaml").write_text(
        "name: " + name + NL + "steps:" + NL + steps + "provider:" + NL
        + "  provider: fake" + NL, encoding="utf-8")
    (folder / "tester.md").write_text("# tester" + NL + NL + "write the test."
                                      + NL, encoding="utf-8")
    (folder / "worker.md").write_text("# worker" + NL + NL + "do the work."
                                      + NL, encoding="utf-8")


def running(tmp_path, monkeypatch, place, flow, does, *args):
    """main() over `flow` in `place`, each step doing what `does` names for
    it: (files it writes, what it answers), or a list of them, one per go.
    -> the steps that were called."""
    called = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        planned = does[step]
        if isinstance(planned, list):
            planned = planned[min(called.count(step), len(planned)) - 1]
        writes, said = planned
        for rel, text in writes.items():
            (place / rel).parent.mkdir(parents=True, exist_ok=True)
            (place / rel).write_text(text, encoding="utf-8")
        return said, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force", "--workdir",
                                      str(place)] + list(args))
    code = engine.main()
    return code, called


def folders():
    assert state.RUNS.is_dir(), "no run was started"
    return sorted((p for p in state.RUNS.iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime_ns)


def read(path):
    return path.read_text(encoding="utf-8")


def test_product_code_before_a_red_proof_is_refused_before_the_call(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({"calc.py": FIXED}, "done")})
    assert called == []
    assert code == stops.exit_code(stops.REFUSED)
    why = read(folders()[-1] / "why.md")
    assert "no red test" in why
    assert read(place / "calc.py") == BUGGY


def test_a_tests_step_editing_product_code_fails(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST, "calc.py": FIXED},
                      TESTER_SAID)})
    assert called == ["tester.md", "tester.md"]
    assert code == stops.exit_code(stops.GATE)
    why = read(folders()[-1] / "why.md")
    assert "writes tests only" in why
    assert "calc.py" in why


def test_a_tests_step_editing_product_code_is_sent_back_and_can_undo_it(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": [({"tests/test_calc.py": RED_TEST,
                        "calc.py": FIXED + "# not the size of the bug" + NL},
                       TESTER_SAID),
                      ({"calc.py": BUGGY}, TESTER_SAID)],
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert called == ["tester.md", "tester.md", "worker.md"]
    assert code == stops.EXIT_OK


def test_a_tests_step_may_write_test_tooling(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST,
                       "conftest.py": "import sys" + NL,
                       "pytest.ini": "[pytest]" + NL,
                       ".coverage": "x",
                       ".hypothesis/examples": "x"}, TESTER_SAID),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK


def test_skip_tests_runs_and_says_so(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--skip-tests", "hotfix")
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    folder = folders()[-1]
    assert "hotfix" in read(folder / "decisions.md")
    assert "tests skipped: hotfix" in read(folder / "handoff.md")


def test_a_carried_continuation_passes(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, _ = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "")})
    assert code != stops.EXIT_OK
    first = folders()[-1].name
    a_flow(tmp_path, "patch", WORKER)
    code, called = running(tmp_path, monkeypatch, place, "patch",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--continue", first)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    assert "tests carried from run " + first in read(folders()[-1]
                                                      / "handoff.md")


def test_a_proof_rewritten_after_its_run_is_not_carried(tmp_path,
                                                       monkeypatch, capsys):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "")})
    first = folders()[-1]
    rewritten = "def test_add():" + NL + "    pass" + NL
    (place / "tests" / "test_calc.py").write_text(rewritten,
                                                  encoding="utf-8")
    proof = json.loads(read(first / redorder.FILE))
    proof["proof"]["tests"] = {"tests/test_calc.py": snapshot._sha(
        rewritten.encode("utf-8"))}
    (first / redorder.FILE).write_text(json.dumps(proof), encoding="utf-8")
    a_flow(tmp_path, "patch", WORKER)
    code, called = running(tmp_path, monkeypatch, place, "patch",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--continue", first.name)
    assert called == []
    assert code == 1
    assert "red-proof.json was changed" in capsys.readouterr().out

def test_a_missing_snapshot_refuses(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "")})
    first = folders()[-1]
    assert (first / "start-snapshot.json").is_file()
    (first / "start-snapshot.json").unlink()
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--resume", first.name])
    called = []
    monkeypatch.setattr(engine, "call", lambda *a, **kw: called.append(1))
    code = engine.main()
    assert called == []
    assert code == stops.exit_code(stops.REFUSED)
    assert "no start snapshot" in read(folders()[-1] / "why.md")


def test_a_resume_carries_the_snapshot_and_the_proof(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "")})
    first = folders()[-1]
    proof = json.loads(read(first / "red-proof.json"))
    assert proof["proof"]["step"] == "tester.md"
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--resume", first.name)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK


def test_a_tests_step_whose_red_test_runs_nothing_is_refused_by_the_checker(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    claimed = ("  - role: tester" + NL + "    prompt: tester.md" + NL
               + "    writes: tests" + NL + "    gates:" + NL
               + "      - gate: red-test" + NL + "        red: true" + NL)
    a_flow(tmp_path, "build", claimed + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID)})
    assert called == []
    assert code == 1


def a_raw(*steps):
    return {"name": "x", "steps": list(steps)}


def test_the_checker_wants_a_commanded_red_test_on_every_tests_step():
    bare = {"role": "tester", "writes": "tests",
            "gates": [{"gate": "red-test", "red": True}]}
    green = {"role": "tester", "writes": "tests",
             "gates": [{"gate": "red-test", "red": False,
                        "command": ["pytest", "{test}"]}]}
    good = {"role": "tester", "writes": "tests",
            "gates": [{"gate": "red-test", "red": True,
                       "command": ["pytest", "{test}"]}]}
    product = {"role": "worker", "writes": "product"}
    for tester in (bare, green):
        bad = spec.check(a_raw(tester, product))
        assert any("red-test gate with red: true and a command" in b
                   for b in bad), bad
    assert spec.check(a_raw(good, product)) == []


def test_the_checker_wants_writes_on_every_step_once_one_says_it():
    bad = spec.check(a_raw({"role": "planner"},
                           {"role": "worker", "writes": "product"}))
    assert any("step 0" in b and "writes" in b for b in bad), bad
    assert spec.check(a_raw({"role": "planner"}, {"role": "worker"})) == []


def test_red_first_on_the_product_step_after_continue_passes(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    before = git(place, "rev-parse", "HEAD").strip()
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "the tests")
    a_flow(tmp_path, "patch", WORKER + RED_GATE.replace(
        "red-test", "red-first").replace("        red: true" + NL, ""))
    code, called = running(tmp_path, monkeypatch, place, "patch",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--continue", before)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    handoff = read(folders()[-1] / "handoff.md")
    assert "carried from " + before[:12] + ", green with the fix" in handoff


def test_uncommitted_tests_are_carried_with_continue_head(tmp_path,
                                                         monkeypatch):
    place = a_repo(tmp_path / "repo")
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    a_flow(tmp_path, "patch", WORKER + RED_GATE.replace(
        "red-test", "red-first").replace("        red: true" + NL, ""))
    code, called = running(tmp_path, monkeypatch, place, "patch",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--continue", "HEAD")
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    assert "tests carried from HEAD" in read(folders()[-1] / "handoff.md")


def test_a_new_test_file_failing_on_import_is_carried_as_red(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    before = git(place, "rev-parse", "HEAD").strip()
    (place / "tests" / "test_mul.py").write_text(
        "from calc import mul" + NL + NL + NL + "def test_mul():" + NL
        + "    assert mul(2, 3) == 6" + NL, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "the tests")
    a_flow(tmp_path, "patch", WORKER + RED_GATE.replace("red: true",
                                                        "red: false"))
    with_mul = BUGGY + NL + NL + "def mul(a, b):" + NL + "    return a * b" + NL
    code, called = running(tmp_path, monkeypatch, place, "patch", {
        "worker.md": ({"calc.py": with_mul}, "TEST: tests/test_mul.py" + NL)},
        "--continue", before)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    proof = json.loads(read(folders()[-1] / "red-proof.json"))["proof"]
    assert proof["kinds"]["tests/test_mul.py"] in ("ImportError",
                                                   "a collection error")


def test_a_red_test_named_with_a_backslash_is_a_proof(tmp_path):
    place = a_repo(tmp_path / "repo")
    order = redorder.Order(snapshot.take(place), cmd=PYTEST)
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    said = "TEST: .\\tests\\test_calc.py" + NL
    assert order.proven("tester.md", [Result("red-test", True, "red, exit 1")],
                        said)


def test_a_spec_is_read_from_the_place_and_a_star_stays_in_its_folder(
        tmp_path):
    repo = a_repo(tmp_path / "repo")
    place = repo / "pkg"
    (place / "docs" / "specs").mkdir(parents=True)
    (place / "TASK.md").write_text("x", encoding="utf-8")
    (place / "docs" / "specs" / "api.md").write_text("x", encoding="utf-8")
    (place / "notes").mkdir()
    (place / "notes" / "SPEC1.md").write_text("x", encoding="utf-8")
    shot = snapshot.take(place)
    assert sorted(shot.specs) == ["pkg/TASK.md", "pkg/docs/specs/api.md"]
    assert "pkg/notes/SPEC1.md" in shot.product


def test_skip_tests_lets_a_tests_step_go_without_its_fails_line(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER.replace(
        "    writes: tests" + NL, "    writes: tests" + NL
        + "    must_produce: \"FAILS:\"" + NL) + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, "no test for a hotfix"),
        "worker.md": ({"calc.py": FIXED}, "done")},
        "--skip-tests", "hotfix")
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK


def test_a_resume_whose_proved_test_moved_refuses(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    a_flow(tmp_path, "build", TESTER + WORKER)
    running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID),
        "worker.md": ({}, "")})
    first = folders()[-1]
    (place / "tests" / "test_calc.py").write_text(
        "def test_add():" + NL + "    assert True" + NL, encoding="utf-8")
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({"calc.py": FIXED}, "done")},
                           "--resume", first.name)
    assert called == []
    assert code == stops.exit_code(stops.REFUSED)
    assert "tests/test_calc.py" in read(folders()[-1] / "why.md")


def test_tests_red_at_the_start_commit_are_carried_from_it(tmp_path,
                                                          monkeypatch):
    place = a_repo(tmp_path / "repo")
    before = git(place, "rev-parse", "HEAD").strip()
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "the tests")
    a_flow(tmp_path, "patch", WORKER + RED_GATE.replace("red: true",
                                                        "red: false"))
    code, called = running(tmp_path, monkeypatch, place, "patch", {
        "worker.md": ({"calc.py": FIXED}, "TEST: tests/test_calc.py" + NL)},
        "--continue", before)
    assert called == ["worker.md"]
    assert code == stops.EXIT_OK
    assert "tests carried from " + before[:12] in read(folders()[-1]
                                                        / "handoff.md")


def test_tests_green_at_the_start_commit_are_not_carried(tmp_path,
                                                        monkeypatch):
    place = a_repo(tmp_path / "repo")
    before = git(place, "rev-parse", "HEAD").strip()
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "the tests and the fix")
    a_flow(tmp_path, "patch", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "patch", {},
                           "--continue", before)
    assert called == []
    assert code == 1


SUPPLIED = "tests/test_bug_report.py"
NAMES_SUPPLIED = "FAILS: assert -1 == 3" + NL + "TEST: " + SUPPLIED + NL


def supplied(place, commit):
    (place / SUPPLIED).parent.mkdir(parents=True, exist_ok=True)
    (place / SUPPLIED).write_text(RED_TEST, encoding="utf-8")
    if commit:
        git(place, "add", ".")
        git(place, "commit", "-qm", "the bug report")


def a_plain_place(where):
    where.mkdir(parents=True)
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    return where


def proof_of_last_run():
    return json.loads(read(folders()[-1] / "red-proof.json"))["proof"]


def test_a_supplied_test_red_at_the_start_commit_is_the_red_proof(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    supplied(place, commit=True)
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, NAMES_SUPPLIED),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK
    proof = proof_of_last_run()
    assert proof["source"] == "supplied"
    assert list(proof["tests"]) == [SUPPLIED]
    assert "supplied" in read(folders()[-1] / "handoff.md")


def test_a_supplied_test_not_yet_committed_is_the_red_proof(tmp_path,
                                                           monkeypatch):
    place = a_repo(tmp_path / "repo")
    supplied(place, commit=False)
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, NAMES_SUPPLIED),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert called == ["tester.md", "worker.md"]
    assert code == stops.EXIT_OK
    assert proof_of_last_run()["source"] == "supplied"


def test_a_supplied_red_test_outside_git_is_not_a_proof(tmp_path):
    place = a_plain_place(tmp_path / "plain")
    (place / "tests").mkdir()
    (place / SUPPLIED).write_text(RED_TEST, encoding="utf-8")
    order = redorder.Order(snapshot.take(place), cmd=PYTEST)
    assert not order.proven("tester.md", [
        Result("red-test", True, "red, exit 1")], NAMES_SUPPLIED)
    assert "no red test" in order.before("worker.md", "product")


def test_a_supplied_red_test_with_no_red_gate_is_still_refused(tmp_path,
                                                              monkeypatch):
    place = a_repo(tmp_path / "repo")
    supplied(place, commit=True)
    a_flow(tmp_path, "build", WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build",
                           {"worker.md": ({"calc.py": FIXED}, "done")})
    assert called == []
    assert code == stops.exit_code(stops.REFUSED)
    assert "no red test" in read(folders()[-1] / "why.md")


def test_a_supplied_test_green_at_the_start_is_still_refused(tmp_path,
                                                            monkeypatch):
    place = a_repo(tmp_path / "repo")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    supplied(place, commit=True)
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, NAMES_SUPPLIED),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert "worker.md" not in called
    assert code != stops.EXIT_OK
    assert "passed before the patch" in read(folders()[-1] / "why.md")


def test_a_supplied_test_the_gate_did_not_run_is_no_proof(tmp_path):
    place = a_repo(tmp_path / "repo")
    supplied(place, commit=True)
    order = redorder.Order(snapshot.take(place), cmd=PYTEST)
    assert not order.proven("tester.md", [
        Result("red-test", True, "red, as claimed - nothing was run")],
        NAMES_SUPPLIED)
    assert not order.proven("tester.md", [
        Result("red-test", False, "the test passed before the patch")],
        NAMES_SUPPLIED)
    assert order.proof is None


def test_a_test_the_run_wrote_is_recorded_as_written(tmp_path):
    place = a_repo(tmp_path / "repo")
    order = redorder.Order(snapshot.take(place), cmd=PYTEST)
    (place / "tests" / "test_calc.py").write_text(RED_TEST, encoding="utf-8")
    assert order.proven("tester.md", [Result("red-test", True, "red, exit 1")],
                        TESTER_SAID)
    assert order.proof["source"] == "written"


GREEN_TEST = RED_TEST
BREAKER = "import calc" + NL + "calc.add = lambda a, b: a - b" + NL


def a_green_supplied_test(place):
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    (place / SUPPLIED).write_text(GREEN_TEST, encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "green")


def test_a_conftest_that_turns_a_green_supplied_test_red_is_no_proof(
        tmp_path, monkeypatch):
    for breaker in ("conftest.py", "tests/conftest.py"):
        place = a_repo(tmp_path / breaker.replace("/", "-") / "repo")
        a_green_supplied_test(place)
        a_flow(tmp_path / breaker.replace("/", "-"), "build", TESTER + WORKER)
        code, called = running(tmp_path / breaker.replace("/", "-"),
                               monkeypatch, place, "build", {
                                   "tester.md": ({breaker: BREAKER},
                                                 NAMES_SUPPLIED),
                                   "worker.md": ({"calc.py": FIXED}, "done")})
        assert "worker.md" not in called, breaker
        assert code == stops.exit_code(stops.REFUSED), breaker


def test_a_supplied_test_that_errors_in_setup_is_no_proof(tmp_path,
                                                         monkeypatch):
    place = a_repo(tmp_path / "repo")
    (place / SUPPLIED).write_text(
        "def test_needs_db(database):" + NL + "    assert database" + NL,
        encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "an old broken test")
    a_flow(tmp_path, "build", TESTER + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, NAMES_SUPPLIED),
        "worker.md": ({"calc.py": FIXED}, "done")})
    assert "worker.md" not in called
    assert code == stops.exit_code(stops.REFUSED)


def test_fix_with_test_on_a_bug_report_with_its_own_red_test_ends_done(
        tmp_path, monkeypatch):
    import shutil

    from agentweft.runner.prompts import flow_path

    place = a_repo(tmp_path / "repo")
    supplied(place, commit=True)
    shutil.copytree(flow_path("fix-with-test"),
                    tmp_path / "flows" / "fix-with-test")
    code, called = running(tmp_path, monkeypatch, place, "fix-with-test", {
        "worker.md": ({}, NAMES_SUPPLIED),
        "patcher.md": ({"calc.py": FIXED}, "patched calc.py" + NL),
        "verify.md": ({}, "VERDICT: ok" + NL + NL + "fine" + NL)},
        "--task", "add(1, 2) gives -1; tests/test_bug_report.py shows it")
    assert called[:2] == ["worker.md", "patcher.md"]
    assert code == stops.EXIT_OK
    assert "supplied, red at the start, green with the fix" in read(
        folders()[-1] / "gates.md")
    handoff = read(folders()[-1] / "handoff.md")
    assert "supplied" in handoff
    assert proof_of_last_run()["source"] == "supplied"


UNRELATED = "tests/test_unrelated.py"
RED_FIRST_GATE = ("    gates:" + NL + "      - gate: red-first" + NL
                  + "        command: [\"python\", \"-m\", \"pytest\","
                  " \"-q\", \"{test}\"]" + NL)


def test_a_supplied_red_the_fix_leaves_red_fails_red_first(tmp_path,
                                                         monkeypatch):
    place = a_repo(tmp_path / "repo")
    (place / UNRELATED).write_text("def test_other():" + NL
                                   + "    assert 1 == 2" + NL,
                                   encoding="utf-8")
    git(place, "add", ".")
    git(place, "commit", "-qm", "an old failing test")
    a_flow(tmp_path, "build", TESTER + WORKER + RED_FIRST_GATE)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({}, "FAILS: assert 1 == 2" + NL + "TEST: " + UNRELATED
                      + NL),
        "worker.md": ({"calc.py": FIXED, "tests/test_calc.py": RED_TEST},
                      "done")})
    assert code != stops.EXIT_OK
    assert UNRELATED + ", supplied, red at the start, does not pass" in read(
        folders()[-1] / "gates.md")
