"""every way each of the ten gates refuses, or says it could not do its job,
has a test of its own. the paths other files already hold are left to them;
these are the ones nothing ran."""
import json
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import gates, snapshot, worktree
from agentweft.guardrails.redorder import Order
from agentweft.orchestrate import workflow

NL = chr(10)
BUGGY = "def add(a, b):" + NL + "    return a - b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL
RED_AND_GREEN = ("from calc import add" + NL + NL + NL + "def test_add():" + NL
                 + "    assert add(1, 2) == 3" + NL + NL + NL
                 + "def test_zero():" + NL + "    assert add(0, 0) == 0" + NL)
GREEN = ("from calc import add" + NL + NL + NL + "def test_zero():" + NL
         + "    assert add(0, 0) == 0" + NL)
FAILING = "def test_old():" + NL + "    assert False" + NL
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
          "{test}"]
# red on the code as it started (calc.py subtracts), and never done with the
# fix, so the run with the fix is the one that times out
RED_THEN_HANGS = [sys.executable, "-c",
                  "import sys, time; src = open('calc.py').read();"
                  " sys.exit(1) if 'a - b' in src else time.sleep(60)",
                  "{test}"]


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_repo(where, old="def test_old():" + NL + "    assert True" + NL):
    where.mkdir(parents=True)
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    (where / "calc.py").write_text(BUGGY, encoding="utf-8")
    (where / "tests").mkdir()
    (where / "tests" / "test_old.py").write_text(old, encoding="utf-8")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def red_first(place, command=PYTEST, order=None, **opts):
    return gates.build(dict({"gate": "red-first", "command": command}, **opts),
                       where=place, start=snapshot.take(place), order=order)


def carried(rel, sha):
    return {"how": "carried", "from": "an earlier run", "tests": {rel: sha}}


def no_tree(*args, **kwargs):
    raise ValueError("git worktree add said no")


# command


def test_command_with_no_command_is_the_gate_s_own_fail():
    r = gates.build({"gate": "command"}).run("x")
    assert not r and r.broke
    assert r.detail == "no command"


# project


def project_yml(tmp_path, monkeypatch, text):
    home = tmp_path / "orchestrate"
    home.mkdir()
    monkeypatch.setattr(workflow, "ROOT", [str(home)])
    (home / "project.yml").write_text(text, encoding="utf-8")


DECLARES_LINT = ("project:" + NL + "  name: here" + NL + "gates:" + NL
                 + "  lint: " + json.dumps([sys.executable, "-c", "pass"]) + NL)


def test_project_with_no_name_is_the_gate_s_own_fail(tmp_path, monkeypatch):
    project_yml(tmp_path, monkeypatch, DECLARES_LINT)
    r = gates.build({"gate": "project"}, where=tmp_path).run("x")
    assert not r and r.broke
    assert r.detail == "no name. the command comes from project.yml"


def test_project_naming_a_gate_project_yml_lacks_fails(tmp_path, monkeypatch):
    project_yml(tmp_path, monkeypatch, DECLARES_LINT)
    r = gates.build({"gate": "project", "name": "tests"},
                    where=tmp_path).run("x")
    assert not r and r.broke
    assert r.detail == "project.yml has no gate tests"


def test_project_with_a_project_yml_that_does_not_check_fails(tmp_path,
                                                              monkeypatch):
    project_yml(tmp_path, monkeypatch, "gates:" + NL + "  lint: "
                + json.dumps([sys.executable, "-c", "pass"]) + NL)
    r = gates.build({"gate": "project", "name": "lint"},
                    where=tmp_path).run("x")
    assert not r and r.broke
    assert r.detail.startswith("project.yml: missing project")


def test_project_with_a_project_yml_that_does_not_read_fails(tmp_path,
                                                             monkeypatch):
    project_yml(tmp_path, monkeypatch, DECLARES_LINT + "gates:" + NL
                + "  lint: []" + NL)
    r = gates.build({"gate": "project", "name": "lint"},
                    where=tmp_path).run("x")
    assert not r and r.broke
    assert r.detail == "project.yml: duplicate key: gates"


# red-first


def test_red_first_on_an_empty_answer_fails_as_one(tmp_path):
    place = a_repo(tmp_path / "repo")
    r = red_first(place).run("  " + NL)
    assert not r and not r.broke
    assert r.detail == "the step answered nothing"


def test_red_first_with_no_test_slot_in_its_command_is_its_own_fail(tmp_path):
    place = a_repo(tmp_path / "repo")
    r = red_first(place, command=[sys.executable, "-m", "pytest"]).run("x")
    assert not r and r.broke
    assert r.detail == "command has to be a list with {test} in it"


def test_red_first_with_no_start_snapshot_passes_saying_it_could_not(
        tmp_path):
    g = gates.build({"gate": "red-first", "command": PYTEST}, where=tmp_path)
    r = g.run("patched it")
    assert r
    assert r.detail == "not replayed - the run took no start snapshot"
    assert r.issue == "could not replay: the run took no start snapshot"


def test_red_first_that_cannot_set_out_the_start_is_its_own_fail(
        tmp_path, monkeypatch):
    place = a_repo(tmp_path / "repo")
    g = red_first(place)
    (place / "tests" / "test_calc.py").write_text(RED_AND_GREEN,
                                                  encoding="utf-8")
    monkeypatch.setattr(worktree, "temporary", no_tree)
    r = g.run("patched it")
    assert not r and r.broke
    assert r.detail == ("could not replay without the fix: git worktree add"
                        " said no")


def test_red_first_on_a_carried_test_file_that_has_changed_fails(tmp_path):
    place = a_repo(tmp_path / "repo")
    g = red_first(place, order=Order(None, proof=carried(
        "tests/test_old.py", "0" * 64)))
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    r = g.run("patched it")
    assert not r and not r.broke
    assert r.detail == ("tests/test_old.py, carried from an earlier run, is"
                        " not the file its red was shown on: a test the fix"
                        " changed shows nothing about the fix")


def test_red_first_on_a_carried_test_still_red_with_the_fix_fails(tmp_path):
    place = a_repo(tmp_path / "repo", old=FAILING)
    sha = snapshot._sha((place / "tests" / "test_old.py").read_bytes())
    g = red_first(place, order=Order(None, proof=carried("tests/test_old.py",
                                                         sha)))
    (place / "tests" / "test_calc.py").write_text(GREEN, encoding="utf-8")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    r = g.run("patched it")
    assert not r
    assert r.detail.startswith("tests/test_old.py, carried from an earlier"
                               " run, does not pass with the fix: red")
    assert [t["before"] for t in r.tests] == ["green"]


def test_red_first_on_a_named_test_green_without_the_fix_fails(tmp_path):
    place = a_repo(tmp_path / "repo")
    g = red_first(place)
    (place / "tests" / "test_calc.py").write_text(RED_AND_GREEN,
                                                  encoding="utf-8")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    r = g.run("TEST: tests/test_calc.py::test_zero" + NL + "patched it")
    assert not r
    assert r.detail == "tests/test_calc.py::test_zero passes without the fix"
    assert sorted((t["test"], t["before"]) for t in r.tests) == [
        ("tests/test_calc.py::test_add", "red"),
        ("tests/test_calc.py::test_zero", "green")]


def test_red_first_on_an_exit_that_is_not_red_fails_as_not_run(tmp_path):
    place = a_repo(tmp_path / "repo")
    g = red_first(place, command=[sys.executable, "-c",
                                  "import sys; sys.exit(3)", "{test}"])
    (place / "tests" / "test_calc.py").write_text(GREEN, encoding="utf-8")
    r = g.run("patched it")
    assert not r and not r.broke
    assert r.detail == ("tests/test_calc.py::test_zero did not run without"
                        " the fix: exit 3")
    assert r.issue == ("could not run tests/test_calc.py::test_zero without"
                       " the fix: exit 3")


def test_red_first_whose_command_is_not_on_path_is_its_own_fail(tmp_path):
    place = a_repo(tmp_path / "repo")
    g = red_first(place, command=["no-such-program-anywhere", "{test}"])
    (place / "tests" / "test_calc.py").write_text(GREEN, encoding="utf-8")
    r = g.run("patched it")
    assert not r and r.broke
    assert r.detail == ("tests/test_calc.py::test_zero did not run without"
                        " the fix: not on PATH")
    assert r.issue == ("could not run tests/test_calc.py::test_zero without"
                       " the fix: not on PATH")


def test_red_first_whose_run_with_the_fix_times_out_says_it_could_not(
        tmp_path):
    place = a_repo(tmp_path / "repo")
    g = red_first(place, command=RED_THEN_HANGS, timeout=3)
    (place / "tests" / "test_calc.py").write_text(GREEN, encoding="utf-8")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    r = g.run("patched it")
    assert not r
    assert r.detail == ("tests/test_calc.py::test_zero does not pass with the"
                        " fix: timed out")
    assert r.issue == ("could not run tests/test_calc.py::test_zero with the"
                       " fix: timed out")
    assert [t["before"] for t in r.tests] == ["red"]


# red-test


def test_red_test_that_cannot_set_out_the_start_is_its_own_fail(tmp_path,
                                                                monkeypatch):
    place = a_repo(tmp_path / "repo")
    g = gates.build({"gate": "red-test", "command": PYTEST}, where=place,
                    start=snapshot.take(place))
    (place / "tests" / "test_calc.py").write_text(RED_AND_GREEN,
                                                  encoding="utf-8")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    monkeypatch.setattr(worktree, "temporary", no_tree)
    r = g.run("FAILS: assert -1 == 3" + NL
              + "TEST: tests/test_calc.py::test_add")
    assert not r and r.broke
    assert r.detail == ("could not set out the start to run it on: git"
                        " worktree add said no")


def test_red_test_that_times_out_says_it_could_not_finish(tmp_path):
    place = a_repo(tmp_path / "repo")
    (place / "tests" / "test_calc.py").write_text(GREEN, encoding="utf-8")
    g = gates.build({"gate": "red-test", "timeout": 3, "command": [
        sys.executable, "-c", "import time; time.sleep(60)", "{test}"]},
        where=place)
    r = g.run("FAILS: it hangs" + NL + "TEST: tests/test_calc.py")
    assert not r and not r.broke
    assert r.detail == "timed out"
    assert r.issue == "could not finish: timed out after 3s"


def test_red_test_with_an_empty_test_line_names_no_test(tmp_path):
    place = a_repo(tmp_path / "repo")
    g = gates.build({"gate": "red-test", "command": PYTEST}, where=place)
    r = g.run("FAILS: assert -1 == 3" + NL + "TEST:" + NL)
    assert not r and not r.broke
    assert r.issue == "could not run a test: no TEST: line names one"
