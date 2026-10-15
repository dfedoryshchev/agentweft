"""no product code is written before a red test exists, unless the run says
skip tests. each run here is in a repo whose steps commit nothing."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts, resume, state, stops

NL = chr(10)
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
RED_TEST = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
            + "    assert add(1, 2) == 3" + NL)
TESTER_SAID = "FAILS: assert -1 == 3" + NL + "TEST: tests/test_calc.py" + NL
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
    it: (files it writes, what it answers). -> the steps that were called."""
    called = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        writes, said = does[step]
        for rel, text in writes.items():
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
    assert called == ["tester.md"]
    assert code == stops.exit_code(stops.GATE)
    why = read(folders()[-1] / "why.md")
    assert "writes tests only" in why
    assert "calc.py" in why


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


def test_a_red_test_gate_that_ran_nothing_is_no_proof(tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    claimed = ("  - role: tester" + NL + "    prompt: tester.md" + NL
               + "    writes: tests" + NL + "    gates:" + NL
               + "      - gate: red-test" + NL + "        red: true" + NL)
    a_flow(tmp_path, "build", claimed + WORKER)
    code, called = running(tmp_path, monkeypatch, place, "build", {
        "tester.md": ({"tests/test_calc.py": RED_TEST}, TESTER_SAID)})
    assert called == ["tester.md"]
    assert code == stops.exit_code(stops.REFUSED)


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
