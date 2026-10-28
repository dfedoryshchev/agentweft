"""a test that fails because the machine could not start a process, an
OSError with a WinError or errno code on every red, says nothing about the
change. the start-tests replay, the `command` gate and red-first's run with
the fix run it once more; a fault that holds is an issue the gate could not
get past, never a spec conflict question or a send-back."""
import json
import subprocess
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import hostfault
from agentweft.providers import cli_provider, fake_provider
from agentweft.runner import engine, prompts, resume, state, stops

NL = chr(10)
RETRO = "retro.md"
BUGGY = "VERSION = 1" + NL + NL + NL + "def add(a, b):" + NL \
    + "    return a - b" + NL
FIXED = "VERSION = 2" + NL + NL + NL + "def add(a, b):" + NL \
    + "    return a + b" + NL
WRONG = "VERSION = 2" + NL + NL + NL + "def add(a, b):" + NL \
    + "    return 0" + NL
FAULT = "OSError('[WinError 87] The parameter is incorrect')"
TOOL = ("import os" + NL + NL + "import calc" + NL + NL + NL
        + "def test_tool_runs():" + NL
        + "    flag = os.environ.get('START_FLAKE', '')" + NL
        + "    if flag and os.path.exists(flag):" + NL
        + "        os.remove(flag)" + NL
        + "        raise " + FAULT + NL
        + "    if os.environ.get('START_FAULT') and calc.VERSION == 2:" + NL
        + "        raise " + FAULT + NL
        + "    if os.environ.get('START_BREAKS') and calc.VERSION == 2:" + NL
        + "        assert calc.add(0, 0) == 1, 'the tool broke'" + NL
        + "    full = os.environ.get('START_RMDIR', '')" + NL
        + "    if full and calc.VERSION == 2:" + NL
        + "        os.makedirs(os.path.join(full, 'd'), exist_ok=True)" + NL
        + "        open(os.path.join(full, 'd', 'f'), 'w').close()" + NL
        + "        os.rmdir(os.path.join(full, 'd'))" + NL)
ADD = ("import os" + NL + NL + "import calc" + NL + NL + NL
       + "def test_add():" + NL
       + "    flag = os.environ.get('NEW_FLAKE', '')" + NL
       + "    if flag and os.path.exists(flag) and calc.VERSION == 2:" + NL
       + "        os.remove(flag)" + NL
       + "        raise " + FAULT + NL
       + "    assert calc.add(1, 2) == 3, 'add is still wrong'" + NL)
TESTER = ("  - role: tester" + NL + "    prompt: tester.md" + NL
          + "    writes: tests" + NL + "    gates:" + NL
          + "      - gate: red-test" + NL + "        red: true" + NL
          + "        command: [\"python\", \"-m\", \"pytest\", \"-q\","
          " \"{test}\"]" + NL)
COMMAND = ("      - gate: command" + NL + "        command: [\"python\","
           " \"-m\", \"pytest\", \"-q\", \"-p\", \"no:cacheprovider\"]" + NL
           + "        expect: 0" + NL)
RED_FIRST = ("      - gate: red-first" + NL + "        command: [\"python\","
             " \"-m\", \"pytest\", \"-q\", \"-p\", \"no:cacheprovider\","
             " \"{test}\"]" + NL)


def worker(*gates):
    return ("  - role: worker" + NL + "    prompt: worker.md" + NL
            + "    writes: product" + NL
            + ("    gates:" + NL + "".join(gates) if gates else ""))


def git(where, *args):
    return subprocess.run(["git", "-C", str(where)] + list(args),
                          capture_output=True, text=True, check=True).stdout


def a_place(where):
    (where / "tests").mkdir(parents=True)
    for rel, text in (("calc.py", BUGGY), ("conftest.py", ""),
                      ("tests/test_tool.py", TOOL)):
        (where / rel).write_text(text, encoding="utf-8")
    git(where, "init", "-q")
    git(where, "config", "user.email", "t@t")
    git(where, "config", "user.name", "t")
    git(where, "config", "commit.gpgsign", "false")
    git(where, "add", ".")
    git(where, "commit", "-qm", "start")
    return where


def a_flow(tmp_path, steps):
    folder = tmp_path / "flows" / "build"
    folder.mkdir(parents=True)
    (folder / "flow.yaml").write_text(
        "name: build" + NL + "steps:" + NL + steps + "provider:" + NL
        + "  provider: fake" + NL, encoding="utf-8")
    for role in ("tester", "worker"):
        (folder / (role + ".md")).write_text("# " + role + NL + NL + "go."
                                             + NL, encoding="utf-8")


def run(tmp_path, monkeypatch, steps, fix=FIXED, flake=None, scored=False):
    """-> (exit code, steps called, the run's folder). `flake` names the
    environment variable whose marker file is made as the worker answers,
    so the next test run to read it fails on the fault once. a run `scored`
    as an eval has no exit code, and its folder is the trail its lines went
    to."""
    place = a_place(tmp_path / "repo")
    a_flow(tmp_path, steps)
    marker = tmp_path / "flake"
    if flake:
        monkeypatch.setenv(flake, str(marker))
    called = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        called.append(step)
        if step == RETRO:
            return fake_provider.NOTHING_TO_KEEP, False
        if step == "tester.md":
            (place / "tests" / "test_add.py").write_text(ADD,
                                                         encoding="utf-8")
            return ("FAILS: assert -1 == 3" + NL + "TEST: tests/test_add.py"
                    + NL), False
        (place / "calc.py").write_text(fix, encoding="utf-8")
        if flake:
            marker.write_text("", encoding="utf-8")
        return "- calc.py: add sums" + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(cli_provider.CliProvider, "version",
                        lambda self: cli_provider.FLOOR)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", tmp_path / "runs" / "journal.md")
    if scored:
        trail = tmp_path / "trail"
        trail.mkdir()
        engine.run_once("build", task="add sums", trail=trail, workdir=place)
        return None, called, trail
    monkeypatch.setattr(sys, "argv", ["run.py", "build", "--force",
                                      "--workdir", str(place)])
    code = engine.main()
    folder = sorted((p for p in state.RUNS.iterdir() if p.is_dir()),
                    key=lambda p: p.stat().st_mtime_ns)[-1]
    return code, called, folder


def gate_lines(folder):
    return [json.loads(l) for l in (folder / "gates.jsonl").read_text(
        encoding="utf-8").split(NL) if l.strip()]


def read(path):
    return path.read_text(encoding="utf-8")


def test_a_start_test_red_once_on_a_host_fault_is_run_again_and_passes(
        tmp_path, monkeypatch):
    code, called, folder = run(tmp_path, monkeypatch, TESTER + worker(),
                               flake="START_FLAKE")
    assert code == stops.EXIT_OK, read(folder / "gates.md")
    assert called == ["tester.md", "worker.md"]
    assert "PASS start-tests" in read(folder / "gates.md")


def test_a_start_test_red_on_a_host_fault_twice_is_an_issue_not_a_conflict(
        tmp_path, monkeypatch):
    monkeypatch.setenv("START_FAULT", "1")
    code, called, folder = run(tmp_path, monkeypatch, TESTER + worker())
    assert called == ["tester.md", "worker.md"]
    assert not (folder / "question.md").exists()
    why = read(folder / "why.md")
    assert "cause      " + stops.GATE in why
    assert "could not run the start tests" in why
    assert "[WinError 87]" in why
    [line] = [l for l in gate_lines(folder) if l["gate"] == "start-tests"]
    assert line["ok"] is False
    assert line["issue"].startswith("start-tests could not run the start"
                                    " tests")


def test_a_suite_red_once_on_a_host_fault_is_run_again_and_not_sent_back(
        tmp_path, monkeypatch):
    code, called, folder = run(tmp_path, monkeypatch,
                               TESTER + worker(COMMAND), flake="START_FLAKE")
    assert called == ["tester.md", "worker.md"], read(folder / "gates.md")
    assert code == stops.EXIT_OK
    assert "PASS command" in read(folder / "gates.md")


def test_a_suite_red_on_a_host_fault_twice_stops_with_an_issue_unsent_back(
        tmp_path, monkeypatch):
    monkeypatch.setenv("START_FAULT", "1")
    code, called, folder = run(tmp_path, monkeypatch,
                               TESTER + worker(COMMAND))
    assert called == ["tester.md", "worker.md"]
    assert code == stops.exit_code(stops.GATE)
    [line] = [l for l in gate_lines(folder) if l["gate"] == "command"]
    assert line["ok"] is False
    assert "[WinError 87]" in line["issue"]


def test_a_scored_run_stops_on_a_host_fault_that_holds_and_sends_none_back(
        tmp_path, monkeypatch):
    monkeypatch.setenv("START_FAULT", "1")
    _, called, trail = run(tmp_path, monkeypatch, TESTER + worker(COMMAND),
                           scored=True)
    assert called == ["tester.md", "worker.md"], called
    steps = [json.loads(l) for l in read(trail / "steps.jsonl").split(NL)
             if l.strip()]
    last = [s for s in steps if s["step"] == "worker.md"][-1]
    assert last["cause"] == stops.GATE
    assert "the fault is the machine's" in last["why"]


def test_a_new_test_red_with_the_fix_on_a_host_fault_once_is_run_again(
        tmp_path, monkeypatch):
    code, called, folder = run(tmp_path, monkeypatch,
                               TESTER + worker(RED_FIRST), flake="NEW_FLAKE")
    assert called == ["tester.md", "worker.md"], read(folder / "gates.md")
    assert code == stops.EXIT_OK
    assert "PASS red-first" in read(folder / "gates.md")


def test_a_new_test_red_with_the_fix_keeps_what_it_printed_in_gates_md(
        tmp_path, monkeypatch):
    code, called, folder = run(tmp_path, monkeypatch,
                               TESTER + worker(RED_FIRST), fix=WRONG)
    said = read(folder / "gates.md").split("## worker.md")[1]
    assert "does not pass with the fix: red" in said
    assert "add is still wrong" in said


def test_a_start_test_stop_is_raised_by_the_check_not_by_the_step(
        tmp_path, monkeypatch):
    monkeypatch.setenv("START_BREAKS", "1")
    code, called, folder = run(tmp_path, monkeypatch, TESTER + worker())
    assert code == stops.exit_code(stops.CONFLICT)
    decision = read(folder / "handoff.md").split("## the one decision")[1] \
        .split("## ")[0]
    assert "raised by the start-tests check, after worker.md" in decision
    assert "raised by worker" not in decision


def spawn_fault():
    """the bare OSError a host raises when it cannot start a process: the
    WinError code exists only on Windows, the errno one is POSIX's."""
    if sys.platform == "win32":
        return OSError(22, "The parameter is incorrect", None, 87)
    return OSError(8, "Exec format error")


def without_the_fix_cannot_start(monkeypatch, place, times):
    """red-first's runs anywhere but the place, the checkout without the fix,
    fail to start `times` times with the bare OSError the host raised."""
    import types

    from agentweft.guardrails.gates import redfirst_gate

    left = [times]

    def run(argv, **kw):
        if kw.get("cwd") != str(place) and left[0]:
            left[0] -= 1
            raise spawn_fault()
        return subprocess.run(argv, **kw)

    monkeypatch.setattr(redfirst_gate, "subprocess", types.SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired))


def red_first_on_a_fix(tmp_path):
    from agentweft.guardrails import gates, snapshot

    place = a_place(tmp_path / "repo")
    g = gates.build({"gate": "red-first", "command": [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "{test}"]}, where=place, start=snapshot.take(place))
    (place / "tests" / "test_add.py").write_text(ADD, encoding="utf-8")
    (place / "calc.py").write_text(FIXED, encoding="utf-8")
    return place, g


def test_a_new_test_that_cannot_start_without_the_fix_once_is_run_again(
        tmp_path, monkeypatch):
    place, g = red_first_on_a_fix(tmp_path)
    without_the_fix_cannot_start(monkeypatch, place, 1)
    r = g.run("patched it")
    assert r, r.detail
    assert [t["before"] for t in r.tests] == ["red"]


def test_a_new_test_that_cannot_start_without_the_fix_twice_is_the_hosts(
        tmp_path, monkeypatch):
    place, g = red_first_on_a_fix(tmp_path)
    without_the_fix_cannot_start(monkeypatch, place, 2)
    r = g.run("patched it")
    assert not r and r.broke
    said = "OSError: " + str(spawn_fault())
    assert r.host == said
    assert r.issue == ("could not run tests/test_add.py::test_add without the"
                       " fix: " + said)


def test_one_fault_on_every_red_is_the_hosts_and_two_are_not():
    said = "OSError: [WinError 87] The parameter is incorrect"
    assert hostfault.same([said, said]) == said
    assert hostfault.same([said, "AssertionError: assert 1 == 2"]) == ""
    assert hostfault.same([said, "OSError: [Errno 22] Invalid argument"]) == ""
    assert hostfault.same([]) == ""
    assert hostfault.same(["TypeError: add() takes 2 arguments"]) == ""
    assert hostfault.same(["FileNotFoundError: [Errno 2] No such file"]) == ""


def test_a_code_bugs_bare_oserror_is_the_changes_red_not_the_hosts():
    for said in ("OSError: [WinError 145] The directory is not empty: 'x'",
                 "OSError: [Errno 39] Directory not empty: 'x'",
                 "OSError: [Errno 22] Invalid argument: 'a:b'",
                 "OSError: [Errno 18] Invalid cross-device link: 'a' -> 'b'"):
        assert hostfault.same([said, said]) == "", said
        assert hostfault.line(said) == "", said


def test_a_spawn_code_is_the_hosts_with_or_without_a_traceback():
    for said in ("OSError: [WinError 87] The parameter is incorrect",
                 "OSError: [WinError 193] %1 is not a valid Win32 application",
                 "OSError: [WinError 2] The system cannot find the file",
                 "OSError: [Errno 7] Argument list too long",
                 "OSError: [Errno 8] Exec format error",
                 "OSError: [Errno 12] Cannot allocate memory"):
        assert hostfault.same([said, said]) == said, said


def test_any_code_is_the_hosts_when_the_traceback_shows_the_spawn():
    said = ("Python\\Lib\\subprocess.py:1538: in _execute_child" + NL
            + "E   OSError: [WinError 206] The filename or extension is too"
            " long")
    assert hostfault.key(said) == "WinError 206"
    assert hostfault.key("E   OSError: [WinError 206] The filename or"
                         " extension is too long") == ""


def test_an_oserror_caught_at_the_spawn_says_where_it_was_raised():
    def _execute_child():
        raise OSError(36, "File name too long")

    def elsewhere():
        raise OSError(36, "File name too long")

    for raiser, host in ((_execute_child, True), (elsewhere, False)):
        try:
            raiser()
        except OSError as e:
            said = hostfault.named(e)
        assert bool(hostfault.line(said)) is host, said


def failed_run(*sections):
    """a pytest run's output: one failure section per (test, traceback),
    then the short summary naming the error each ended on."""
    out = "FF" + NL + "=== FAILURES ===" + NL
    for test, trace in sections:
        out = out + "___ " + test + " ___" + NL + NL + trace + NL
    out = out + "=== short test summary info ===" + NL
    for test, trace in sections:
        out = out + "FAILED tests/test_t.py::" + test + " - " \
            + trace.splitlines()[-1][4:] + NL
    return out + str(len(sections)) + " failed"


def test_a_run_whose_reds_are_a_code_bugs_bare_oserror_is_no_fault():
    bug = ("tests/test_t.py:9: in test_tidy" + NL + "    os.rmdir(d)" + NL
           + "E   OSError: [WinError 145] The directory is not empty: 'd'")
    assert hostfault.of_run(failed_run(("test_tidy", bug),
                                       ("test_tidy_again", bug))) == ""


def test_a_run_whose_every_red_shows_the_spawn_is_the_hosts():
    spawn = ("tests/test_t.py:9: in test_tool" + NL + "    run(['tool'])" + NL
             + "/usr/lib/python3/subprocess.py:1955: in _execute_child" + NL
             + "E   OSError: [Errno 36] File name too long: 'tool'")
    assert hostfault.of_run(failed_run(("test_tool", spawn))) == \
        "OSError: [Errno 36] File name too long: 'tool'"
    bug = ("tests/test_t.py:9: in test_tidy" + NL
           + "E   OSError: [Errno 36] File name too long: 'tool'")
    assert hostfault.of_run(failed_run(("test_tool", spawn),
                                       ("test_tidy", bug))) == ""


def test_a_command_gate_red_on_a_code_bugs_oserror_is_the_steps(tmp_path):
    from agentweft.guardrails import gates

    (tmp_path / "test_tidy.py").write_text(
        "import os" + NL + NL + NL + "def test_tidy(tmp_path):" + NL
        + "    (tmp_path / 'd').mkdir()" + NL
        + "    (tmp_path / 'd' / 'f').write_text('')" + NL
        + "    os.rmdir(str(tmp_path / 'd'))" + NL, encoding="utf-8")
    g = gates.build({"gate": "command", "expect": 0, "command": [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "test_tidy.py"]}, where=tmp_path)
    r = g.run("tidied it")
    assert not r and not r.broke, r.detail
    assert r.host == ""
    assert "run again" not in r.detail


def test_a_start_test_red_on_a_code_bugs_oserror_is_a_conflict_not_a_fault(
        tmp_path, monkeypatch):
    monkeypatch.setenv("START_RMDIR", str(tmp_path / "full"))
    code, called, folder = run(tmp_path, monkeypatch, TESTER + worker())
    why = read(folder / "why.md")
    assert "cause      " + stops.CONFLICT in why, why
    assert "the machine" not in why
    assert (folder / "question.md").exists()


def test_the_faults_are_read_off_a_test_runs_short_summary():
    out = ("F." + NL + "=== short test summary info ===" + NL
           + "FAILED tests/test_tool.py::test_tool_runs - OSError: [WinError"
           " 87] The parameter is incorrect" + NL + "1 failed, 1 passed")
    assert hostfault.of_run(out) == ("OSError: [WinError 87] The parameter is"
                                     " incorrect")


def test_an_error_a_running_process_raised_in_subprocess_is_the_code_s():
    said = ("/usr/lib/python3/subprocess.py:1209: in communicate" + NL
            + "E   OSError: [Errno 22] Invalid argument")
    assert hostfault.key(said) == ""
    started = ("/usr/lib/python3/subprocess.py:1955: in _execute_child" + NL
               + "E   OSError: [Errno 22] Invalid argument")
    assert hostfault.key(started) == "Errno 22"
