"""a step ends when its answer arrives, and whatever it left running is ended
with it. these start real processes: a pipe held open by a grandchild is only
proven where an operating system sits in between."""
import os
import subprocess
import sys
import time
import types

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.providers import cli_provider
from agentweft.runner import trace

# the shell and the cli stay on past the step's timeout, so a step that waited
# on either runs into it: held to the timeout, not to a few seconds a busy
# machine runs past
CEILING = 60
OUTLASTS = CEILING * 2
LATE = 3

LEAVES_A_SHELL = r"""
import json, subprocess, sys, time
{before}
sys.stdin.buffer.read()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({sleep})"],
                         stdout=sys.stdout, stderr=sys.stderr)
open({pids!r}, "a").write(str(child.pid) + "\n")
{noise}
{answer}
sys.stdout.flush()
{after}
"""

ANSWER = ('sys.stdout.write(json.dumps({"type": "result", "is_error": False, '
          '"result": "the answer", "session_id": "s-1"}) + "\\n")')


def alive(pid):
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def gone(pid, within=CEILING):
    end = time.time() + within
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """-> a function writing a fake cli and putting it behind the provider;
    every child it starts is ended at teardown, whatever the test did."""
    pids = tmp_path / "children.txt"

    def make(answer=True, noise="", after="", command="claude", before=""):
        script = tmp_path / "fake_cli.py"
        script.write_text(LEAVES_A_SHELL.format(
            sleep=OUTLASTS, pids=str(pids), noise=noise, before=before,
            answer=ANSWER if answer else "", after=after), encoding="utf-8")

        def real(argv):
            return [sys.executable, str(script)] + list(argv[1:])

        monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
            run=lambda argv, **kw: subprocess.run(real(argv), **kw),
            Popen=lambda argv, **kw: subprocess.Popen(real(argv), **kw),
            TimeoutExpired=subprocess.TimeoutExpired))
        return providers.build({"provider": "cli", "command": command})

    make.children = lambda: [int(n) for n in pids.read_text().split()] \
        if pids.exists() else []
    yield make
    for pid in make.children():
        if alive(pid):
            os.kill(pid, 9)


def asked(p):
    """-> the reply, once it is shown the step ended before its timeout: a
    step held to its timeout still keeps an answer it had, so a reply with no
    detail does not show that."""
    began = time.time()
    r = p.ask("go", timeout=CEILING)
    took = time.time() - began
    assert not r.detail, r.detail
    assert took < CEILING, "ran its whole %ds timeout" % CEILING
    return r


def test_an_answer_ends_the_step_and_the_shell_left_behind(fake):
    r = asked(fake())
    assert r.text == "the answer"
    assert getattr(r, "killed", None) == 1
    [child] = fake.children()
    assert gone(child)


def test_an_answer_ends_a_cli_that_stays_on_after_it(fake):
    """the cli itself waiting on its background shell after it has answered."""
    r = asked(fake(after="time.sleep(%d)" % OUTLASTS))
    assert r.text == "the answer"
    assert getattr(r, "killed", None) == 1
    [child] = fake.children()
    assert gone(child)


def test_a_cli_slow_to_start_still_ends_on_its_answer(fake):
    """an answer that comes late, as on a busy machine, ends the step as one
    on time does."""
    r = asked(fake(before="time.sleep(%d)" % LATE,
                   after="time.sleep(%d)" % OUTLASTS))
    assert r.text == "the answer"
    assert getattr(r, "killed", None) == 1
    [child] = fake.children()
    assert gone(child)


def test_a_timeout_leaves_nothing_running(fake):
    p = fake(answer=False, after="time.sleep(%d)" % OUTLASTS)
    # a cli slower to start than the timeout is ended before it starts its
    # shell, which proves nothing, so the timeout grows until it fires on one
    for timeout in (2, 8, 30):
        began = time.time()
        r = p.ask("go", timeout=timeout)
        took = time.time() - began
        if fake.children():
            break
    assert took < CEILING, "a %ds timeout took %.1fs" % (timeout, took)
    assert r.detail == "timed out after %ds" % timeout and r.retryable
    [child] = fake.children()
    assert gone(child), "the shell outlived the timeout"


def test_another_command_that_exits_is_not_held_by_its_shell(fake):
    r = asked(fake(command="sometool"))
    assert "the answer" in r.text
    assert getattr(r, "killed", None) == 1


def test_a_loud_stderr_does_not_stall_the_answer(fake):
    r = asked(fake(noise='sys.stderr.write("e" * 2000000); '
                         'sys.stderr.flush()'))
    assert r.text == "the answer"


def test_a_step_line_says_how_many_shells_were_ended():
    class Said(object):
        name, command = "cli", "claude"

        def asks_for(self):
            return None

        def granted(self):
            return None

    a = trace.Attempt()
    a.seconds = 1.0
    a.replies = [types.SimpleNamespace(usage=None, cost=None, session=None,
                                       model=None, killed=n) for n in (1, 2)]
    a.retries = {}
    entry = trace.Entry(1, "planner", [a], Said(), None, None, False)
    line = trace.line(entry, "ok")
    assert line.get("background_killed") == 3
