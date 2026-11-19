"""a spec line the code already breaks for a sibling path is fixed test-first,
never stopped on and never extended.

a plan may mark a behaviour `spec: breaks <spec line>, already at <file>:<line>
"<quote>"`. the runner checks the quote is on that line of the code as the
run found it, and the plan carries a behaviour `fix: <spec line> for <the
sibling path>`; then the mark does not stop the run. the test writer names
the sibling's test on a `SIBLING TEST:` line, and the runner shows three
effects of it. at the test writer: the test, one this run added, is red in a
checkout of the start commit on an assertion or on an error raised in a
product file the run started with, and that run executes the marked code
line (`sibling-red` on its line); a missing name, an error raised in the
test file, a marked line never reached, a pass, or a test the run did not
add parks there, before any code is written. at the end: the test passes,
and fails again with the function holding the marked code line put back as
the run found it, everything else as the run left it; then the runner's own
line holds `already-broken` and the handoff lists it first among the defects
fixed beside the change, with the test's assert lines. any miss parks on the
mark as a plain `breaks`, the failed effect named, and nothing passes. the
runner never checks the test asserts what the spec line says.
"""
import json
import subprocess
import sys
import types

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from agentweft.guardrails import blocks, snapshot
from agentweft.runner import asking, engine, ruling, spend, stops, wouldpass

import test_lead as tl

NL = chr(10)
BROKEN = "def add(a, b):" + NL + "    return a - b" + NL
MUL = NL + NL + "def mul(a, b):" + NL + "    return a * b" + NL
FIXED = "def add(a, b):" + NL + "    return a + b" + NL + MUL
MARK = 'spec: breaks TASK.md:3, already at calc.py:2 "return a - b"'


def plan_of(mark, fix="TASK.md:3 for add, which returns a minus b"):
    return NL.join(["- behaviour: mul(2, 3) is 6", "  file: calc.py",
                    "  " + mark, "- behaviour: fix: " + fix,
                    "  file: calc.py", "  spec: allows " + fix.split()[0],
                    ""])


PLAN = plan_of(MARK)
SIBLING_ID = "tests/test_mul.py::test_add_sibling"
ALL = ["planner.md", "tester.md", "worker.md", "reviewer.md",
       "reviewer-runs.md"]


def with_sibling(sibling, name="test_add_sibling", imports="add"):
    return (tl.TEST + NL + NL + "def " + name + "():" + NL
            + "    from calc import " + imports + NL + NL + "    assert "
            + sibling + NL)


def run(tmp_path, monkeypatch, plan=PLAN, sibling="add(2, 1) == 3",
        tester=tl.TESTER + "SIBLING TEST: " + SIBLING_ID + NL,
        before=BROKEN, fixed=FIXED, tests=None, start=()):
    monkeypatch.setattr(tl, "BEFORE", before)
    answers = {"planner.md": [plan], "tester.md": [tester],
               "worker.md": [tl.WORKER], "reviewer.md": [tl.OK],
               "reviewer-runs.md": [tl.OK]}
    writes = {"tester.md": [("tests/test_mul.py",
                             tests or with_sibling(sibling))],
              "worker.md": [("calc.py", fixed)]}
    return tl.run_it(tmp_path, monkeypatch, "build-feature", answers, writes,
                     start=start)


def steps_of(folder):
    return [json.loads(l) for l in (folder / "steps.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]


def gate_names(folder):
    return [(s["step"], g["gate"]) for s in steps_of(folder)
            for g in s.get("gates") or ()]


def question(folder):
    return (folder / "question.md").read_text(encoding="utf-8")


def beside_first(folder):
    handoff = (folder / "handoff.md").read_text(encoding="utf-8")
    beside = handoff.split("## found beside the change")[1].split(NL + "## ")[0]
    return beside.strip().split(NL)[0]


def test_the_second_form_holds_only_with_its_quote_on_the_code_line(
        tmp_path):
    (tmp_path / "calc.py").write_text(BROKEN, encoding="utf-8")
    (tmp_path / "TASK.md").write_text(tl.SPEC, encoding="utf-8")
    assert ruling.already_at(MARK, str(tmp_path)) == ("TASK.md:3", "calc.py:2")
    assert ruling.already_at(MARK.replace("a - b", "a * b"),
                             str(tmp_path)) is None
    assert ruling.already_at("spec: breaks TASK.md:3", str(tmp_path)) is None


def test_a_line_already_broken_for_a_sibling_is_fixed_test_first(
        tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch)
    assert asked == ALL + [tl.RETRO]
    assert code == stops.EXIT_OK
    first = beside_first(folder)
    assert first.startswith("- runner: TASK.md:3 already broken at calc.py:2,"
                            " red on the start commit (assertion), green now,"
                            " red again with `add` put back as found")
    assert "the test asserts: assert add(2, 1) == 3" in first
    assert "fixed, shown by " + SIBLING_ID in first
    names = gate_names(folder)
    assert ("tester.md", "sibling-red") in names
    assert ("runner", "already-broken") in names
    assert [n for n in names if n[1] == "already-broken"] == [
        ("runner", "already-broken")]
    assert "handoff missing: runner" not in (folder / "handoff.md").read_text(
        encoding="utf-8")
    assert not (folder / asking.RECORD).exists()
    assert not (folder / asking.KEPT / "calc.py").exists()
    lines = steps_of(folder)
    [runner] = [l for l in lines if l["step"] == "runner"]
    with_runner, without = spend.Group(), spend.Group()
    for line in lines:
        with_runner.add("r", line)
        if line is not runner:
            without.add("r", line)
    assert with_runner.line("r") == without.line("r")
    assert blocks.calls_of(runner) == 0
    retro = (folder / "handoff.md").read_text(encoding="utf-8").split(
        "## retro")[1]
    assert [l for l in retro.split(NL) if l.startswith("- runner ")][0] \
        .split(")")[0].endswith("(no call")


def test_a_sibling_test_green_on_the_start_tree_parks_as_a_break(
        tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch,
                                    sibling="add(2, 1) == 1")
    assert asked == ["planner.md", "tester.md"]
    assert code == stops.EXIT_STOP
    assert "passes on the code as the run found it" in question(folder)
    assert MARK in question(folder)


def test_no_sibling_test_named_parks_as_a_break(tmp_path, monkeypatch):
    asked, _, code, folder, _ = run(tmp_path, monkeypatch, tester=tl.TESTER)
    assert asked == ["planner.md", "tester.md"]
    assert code == stops.EXIT_STOP
    assert "names no SIBLING TEST" in question(folder)


def test_the_second_form_with_no_fix_planned_parks_as_today(tmp_path,
                                                            monkeypatch):
    plan = NL.join(PLAN.split(NL)[:3]) + NL
    asked, _, code, _, _ = run(tmp_path, monkeypatch, plan=plan)
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP


def test_a_quote_not_on_the_cited_code_line_parks_as_today(tmp_path,
                                                           monkeypatch):
    asked, _, code, _, _ = run(tmp_path, monkeypatch,
                               plan=PLAN.replace("a - b\"", "a / b\""))
    assert asked == ["planner.md"]
    assert code == stops.EXIT_STOP


CORRECT = "def add(a, b):" + NL + "    return a + b" + NL
SOUND = 'spec: breaks TASK.md:3, already at calc.py:2 "return a + b"'
COMMENTED = ("def add(a, b):" + NL + "    # the sum" + NL + "    return a + b"
             + NL + MUL)
WIDENED = ("def add(a, b, times=False):" + NL + "    if times:" + NL
           + "        return a * b" + NL + "    return a + b" + NL + MUL)


@pytest.mark.parametrize("wrote, named, body, imports, why", [
    (COMMENTED, "test_mul_is_there", "mul(2, 3) == 6", "mul",
     "on a missing name (ImportError), so it is a test of the new path"),
    (WIDENED, "test_add_times", "add(2, 3, times=True) == 6", "add",
     "by TypeError raised in tests/test_mul.py, not in the code as the run"
     " found it"),
], ids=["comment in the block, feature test named",
        "feature built into the marked function"])
def test_a_test_of_the_new_path_named_as_the_sibling_parks_at_the_tester(
        tmp_path, monkeypatch, wrote, named, body, imports, why):
    test = "tests/test_mul.py::" + named
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch, plan=plan_of(SOUND, "TASK.md:3 for add"),
        before=CORRECT, fixed=wrote,
        tester=tl.TESTER + "SIBLING TEST: " + test + NL,
        tests=with_sibling(body, named, imports))
    assert code == stops.EXIT_STOP
    assert asked == ["planner.md", "tester.md"]
    assert test + " is red on the start commit " + why in question(folder)
    assert SOUND in question(folder)


DISPATCH = ("def main(argv):" + NL + "    if argv[0] == 'add':" + NL
            + "        return 0" + NL + "    return 2" + NL)
WITH_VERB = ("def main(argv):" + NL + "    if argv[0] == 'add':" + NL
             + "        return 0" + NL + "    if argv[0] == 'mul':" + NL
             + "        return 0" + NL + "    return 2" + NL + MUL)
CAUGHT = (tl.TEST + NL + NL + "def test_add_times():" + NL
          + "    from calc import add" + NL + NL + "    try:" + NL
          + "        r = add(2, 3, times=True)" + NL
          + "    except TypeError:" + NL + "        r = None" + NL
          + "    assert r == 6" + NL)


@pytest.mark.parametrize("before, mark, fixed, named, tests", [
    (DISPATCH, 'spec: breaks TASK.md:3, already at calc.py:3 "return 0"',
     WITH_VERB, "test_main_knows_mul",
     with_sibling("main(['mul']) == 0", "test_main_knows_mul", "main")),
    (CORRECT, SOUND, WIDENED, "test_add_times", CAUGHT),
], ids=["a new branch of the marked function asserted by its outcome",
        "a new keyword's error caught in the test"])
def test_a_sibling_test_that_never_runs_the_marked_line_parks_at_the_tester(
        tmp_path, monkeypatch, before, mark, fixed, named, tests):
    """red on the start commit by an assertion, but the marked line never
    ran there: the test is about the new path, not the line the mark names."""
    test = "tests/test_mul.py::" + named
    at = mark.split("already at ")[1].split()[0]
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch, plan=plan_of(mark, "TASK.md:3 for it"),
        before=before, fixed=fixed,
        tester=tl.TESTER + "SIBLING TEST: " + test + NL, tests=tests)
    assert code == stops.EXIT_STOP
    assert asked == ["planner.md", "tester.md"]
    assert test + " never reaches " + at + " on the start commit" \
        in question(folder)
    assert mark in question(folder)


GUARDED = "def add(a, b):" + NL + "    r = a - b" + NL + "    return r" + NL
HELPER = ("def add(a, b):" + NL + "    return _sum(a, b)" + NL + NL + NL
          + "def _sum(a, b):" + NL + "    return a + b" + NL + MUL)


@pytest.mark.parametrize("before, mark, fixed", [
    (GUARDED, 'spec: breaks TASK.md:3, already at calc.py:3 "return r"',
     "def add(a, b):" + NL + "    r = a + b" + NL + "    return r" + NL + MUL),
    (BROKEN, MARK, HELPER),
], ids=["a fix above the line inside the function",
        "a helper elsewhere called from the function"])
def test_a_fix_inside_the_marked_function_is_shown(tmp_path, monkeypatch,
                                                   before, mark, fixed):
    """the function holding the marked line is the unit: a change above the
    line in it, or a call it makes to new code, goes out with the function
    when it is put back."""
    asked, _, code, folder, _ = run(tmp_path, monkeypatch, plan=plan_of(mark),
                                    before=before, fixed=fixed)
    assert code == stops.EXIT_OK, question(folder)
    assert asked == ALL + [tl.RETRO]
    assert "red again with `add` put back as found" in beside_first(folder)


TWO = (CORRECT + NL + NL + "def sub(a, b):" + NL + "    return add(a, b)"
       + NL)
SUB_FIXED = (CORRECT + NL + NL + "def sub(a, b):" + NL
             + "    return add(a, -b)" + NL + MUL)
SUB_ID = "tests/test_mul.py::test_sub_sibling"


def test_a_fix_in_another_function_of_the_file_parks_at_the_end(
        tmp_path, monkeypatch):
    """the mark names add's line and the change fixes sub, which calls add:
    the named test runs add's line and is red on the start commit, green
    now, but add put back as found leaves it green. the tester's `sibling-red` stays on its line; no
    `already-broken` is written anywhere."""
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch, plan=plan_of(SOUND, "TASK.md:3 for sub"),
        before=TWO, fixed=SUB_FIXED,
        tester=tl.TESTER + "SIBLING TEST: " + SUB_ID + NL,
        tests=with_sibling("sub(3, 1) == 2", "test_sub_sibling", "sub"))
    assert code == stops.EXIT_STOP
    assert asked == ALL
    said = question(folder)
    assert "does not show it fixed" in said
    assert SUB_ID + " still passes with `add` put back as found" in said
    assert SOUND in said
    names = gate_names(folder)
    assert ("tester.md", "sibling-red") in names
    assert "already-broken" not in [n[1] for n in names]
    assert "already-broken" not in (folder / "gates.md").read_text(
        encoding="utf-8")


def test_a_marked_function_gone_from_the_final_file_parks(tmp_path,
                                                          monkeypatch):
    rebound = ("def plus(a, b):" + NL + "    return a + b" + NL + NL + NL
               + "add = plus" + MUL)
    asked, _, code, folder, _ = run(tmp_path, monkeypatch, fixed=rebound)
    assert code == stops.EXIT_STOP
    assert asked == ALL
    assert "`add` is not a function in calc.py as the run leaves it" \
        in question(folder)


def test_a_test_the_run_did_not_add_cannot_be_the_sibling(tmp_path,
                                                          monkeypatch):
    red_already = ("def test_sub():" + NL + "    from calc import add" + NL
                   + NL + "    assert add(3, 1) == 2" + NL)
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch,
        tester=tl.TESTER + "SIBLING TEST: tests/test_sub.py::test_sub" + NL,
        start=[("tests/test_sub.py", red_already)])
    assert code == stops.EXIT_STOP
    assert asked == ["planner.md", "tester.md"]
    assert "tests/test_sub.py::test_sub is not a test this run added" \
        in question(folder)


def test_a_sibling_the_start_code_crashes_on_is_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "SPEC", tl.SPEC
                        + "a non-number is `error: not a number`" + NL)
    mark = 'spec: breaks TASK.md:4, already at calc.py:2 "return a + b"'
    guarded = ("def add(a, b):" + NL + "    if isinstance(a, str) or"
               " isinstance(b, str):" + NL
               + "        return \"error: not a number\"" + NL
               + "    return a + b" + NL + MUL)
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch, plan=plan_of(mark, "TASK.md:4 for add"),
        before=CORRECT, fixed=guarded,
        sibling='add("2", 1) == "error: not a number"')
    assert code == stops.EXIT_OK, question(folder)
    gates = (folder / "gates.md").read_text(encoding="utf-8")
    tester = gates.split("## tester.md")[-1]
    assert "sibling-red" in tester
    assert "TypeError raised at calc.py:2" in tester


def git(where, *args):
    subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t", "-c",
                    "user.name=t"] + list(args), check=True,
                   capture_output=True)


def started(tmp_path, cmd=("python", "-m", "pytest", "-q", "{test}"),
            sub="."):
    """-> a run whose start commit holds BROKEN and whose working tree holds
    the fix and the sibling test, in the folder `sub` of the repository."""
    repo = tmp_path / "place"
    project = repo / sub
    (project / "tests").mkdir(parents=True)
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "calc.py").write_text(BROKEN, encoding="utf-8")
    (project / "TASK.md").write_text(tl.SPEC, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "start")
    start = snapshot.take(project)
    (project / "calc.py").write_text(FIXED, encoding="utf-8")
    (project / "tests" / "test_mul.py").write_text(
        with_sibling("add(2, 1) == 3"), encoding="utf-8")
    return types.SimpleNamespace(
        start=start, workdir=str(project), fm=types.SimpleNamespace(
            steps=[{"gates": [{"gate": "red-test", "command": list(cmd)}]}]))


@pytest.mark.parametrize("sub", [".", "app" + chr(0xE9) + " dir"],
                         ids=["the repository root", "a non-ascii folder"])
def test_the_red_on_the_start_commit_is_read_there_not_in_the_tree(
        tmp_path, sub):
    place = started(tmp_path, sub=sub)
    assert asking.sibling_red(place, SIBLING_ID, ["calc.py:2"]) == (
        "assertion", "")
    assert wouldpass.alone(place, [SIBLING_ID]) is False


@pytest.mark.parametrize("at, cmd, why", [
    ("TASK.md:3", ("python", "-m", "pytest", "-q", "{test}"),
     " cannot be shown to reach TASK.md:3 on the start commit: not python"),
    ("calc.py:2", ("python", "-E", "-m", "pytest", "-q", "{test}"),
     " ran where no line probe loaded, so nothing shows it reaches"
     " calc.py:2"),
], ids=["a marked line in a file that is not python",
        "a test command whose python skips the probe"])
def test_a_marked_line_no_probe_can_see_is_never_shown_reached(tmp_path, at,
                                                              cmd, why):
    place = started(tmp_path, cmd)
    assert asking.sibling_red(place, SIBLING_ID, [at]) == (None,
                                                           SIBLING_ID + why)


def test_a_resume_after_the_end_park_carries_on_with_no_proof_run_again(
        tmp_path, monkeypatch):
    """the mark the run stopped on at its end is carried as not shown
    broken: a resume answered on it runs the last step again and finishes,
    and neither
    proves the mark nor writes `already-broken`. what the operator answered
    is the ruling on it."""
    asked, _, code, folder, _ = run(
        tmp_path, monkeypatch, plan=plan_of(SOUND, "TASK.md:3 for sub"),
        before=TWO, fixed=SUB_FIXED,
        tester=tl.TESTER + "SIBLING TEST: " + SUB_ID + NL,
        tests=with_sibling("sub(3, 1) == 2", "test_sub_sibling", "sub"))
    assert code == stops.EXIT_STOP
    monkeypatch.setattr(sys, "argv", [
        "run.py", "build-feature", "--force", "--flows", str(tl.FLOWS),
        "--resume", folder.name, "--answer", "the add line is fine as it is"])
    assert engine.main() == stops.EXIT_OK
    assert asked[len(ALL):] == ["reviewer-runs.md", tl.RETRO]
    [again] = [p for p in (tmp_path / "runs").iterdir()
               if p.is_dir() and p != folder]
    assert "already-broken" not in [n[1] for n in gate_names(again)]
    assert "sibling-red" not in [n[1] for n in gate_names(again)]


def stopped_mid_check(tmp_path):
    """-> (run folder, place, the kept copy): a sibling check put BROKEN
    over the run's FIXED calc.py and the run was killed before it put it
    back."""
    folder, place = tmp_path / "run", tmp_path / "place"
    place.mkdir()
    folder.mkdir()
    (place / "calc.py").write_bytes(BROKEN.encode("utf-8"))
    asking.keep(folder, "calc.py", FIXED.encode("utf-8"),
                BROKEN.encode("utf-8"))
    return folder, place, folder / asking.KEPT / "calc.py"


def test_a_rewritten_file_left_by_a_stopped_check_is_put_back(tmp_path):
    folder, place, kept = stopped_mid_check(tmp_path)
    assert not (folder / "tmp").exists()
    assert asking.restore_kept(folder, str(place)) == ["calc.py"]
    assert (place / "calc.py").read_text(encoding="utf-8") == FIXED
    assert not kept.exists()
    assert not (folder / asking.RECORD).exists()
    assert asking.restore_kept(folder, str(place)) == []


def test_a_file_under_the_steps_scratch_is_never_put_in_the_place(tmp_path):
    """a step may write the run's tmp folder; a copy there is not one the
    runner kept, and no record names it."""
    folder, place = tmp_path / "run", tmp_path / "place"
    (folder / "tmp" / "kept").mkdir(parents=True)
    place.mkdir()
    (place / "TASK.md").write_text("the spec" + NL, encoding="utf-8")
    (folder / "tmp" / "kept" / "TASK.md").write_text("written" + NL,
                                                     encoding="utf-8")
    assert asking.restore_kept(folder, str(place)) == []
    assert (place / "TASK.md").read_text(encoding="utf-8") == "the spec" + NL


@pytest.mark.parametrize("change", ["place", "copy", "record"], ids=[
    "the place changed after the stop", "the copy is not the one kept",
    "the record names a path out of the place"])
def test_a_kept_copy_whose_hashes_do_not_match_is_left(tmp_path, change):
    folder, place, kept = stopped_mid_check(tmp_path)
    if change == "place":
        (place / "calc.py").write_text("edited by hand" + NL,
                                       encoding="utf-8")
    elif change == "copy":
        kept.write_text("not the copy" + NL, encoding="utf-8")
    else:
        said = json.loads((folder / asking.RECORD).read_text(
            encoding="utf-8"))
        said["rel"] = "../calc.py"
        (folder / asking.RECORD).write_text(json.dumps(said),
                                            encoding="utf-8")
        (tmp_path / "calc.py").write_text(BROKEN, encoding="utf-8")
    before = (place / "calc.py").read_bytes()
    assert asking.restore_kept(folder, str(place)) == []
    assert (place / "calc.py").read_bytes() == before
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == BROKEN \
        if change == "record" else True
    assert kept.exists()
