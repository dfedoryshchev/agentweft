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

SLEEP = 15

LEAVES_A_SHELL = r"""
import json, subprocess, sys, time
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


def gone(pid, within=5):
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

    def make(answer=True, noise="", after="", command="claude"):
        script = tmp_path / "fake_cli.py"
        script.write_text(LEAVES_A_SHELL.format(
            sleep=SLEEP, pids=str(pids), noise=noise,
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


def test_an_answer_ends_the_step_and_the_shell_left_behind(fake):
    p = fake()
    began = time.time()
    r = p.ask("go", timeout=SLEEP * 2)
    took = time.time() - began
    assert took < SLEEP / 3, "waited %.1fs for a shell the answer left" % took
    assert r.text == "the answer"
    assert getattr(r, "killed", None) == 1
    [child] = fake.children()
    assert gone(child)


def test_an_answer_ends_a_cli_that_stays_on_after_it(fake):
    """the cli itself waiting on its background shell after it has answered."""
    p = fake(after="time.sleep(%d)" % SLEEP)
    began = time.time()
    r = p.ask("go", timeout=SLEEP * 2)
    took = time.time() - began
    assert took < SLEEP / 2, "waited %.1fs after the answer" % took
    assert r.text == "the answer" and not r.detail
    assert getattr(r, "killed", None) == 1
    [child] = fake.children()
    assert gone(child)


def test_a_timeout_leaves_nothing_running(fake):
    p = fake(answer=False, after="time.sleep(%d)" % SLEEP)
    began = time.time()
    r = p.ask("go", timeout=2)
    took = time.time() - began
    assert took < SLEEP / 2, "a 2s timeout took %.1fs" % took
    assert r.detail == "timed out after 2s" and r.retryable
    [child] = fake.children()
    assert gone(child), "the shell outlived the timeout"


def test_another_command_that_exits_is_not_held_by_its_shell(fake):
    p = fake(command="sometool")
    began = time.time()
    r = p.ask("go", timeout=SLEEP * 2)
    took = time.time() - began
    assert took < SLEEP / 3, "waited %.1fs for a shell the command left" % took
    assert "the answer" in r.text
    assert getattr(r, "killed", None) == 1


def test_a_loud_stderr_does_not_stall_the_answer(fake):
    p = fake(noise='sys.stderr.write("e" * 2000000); sys.stderr.flush()')
    began = time.time()
    r = p.ask("go", timeout=SLEEP * 2)
    assert time.time() - began < SLEEP / 3
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
