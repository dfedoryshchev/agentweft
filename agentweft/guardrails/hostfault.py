"""an error the machine raised starting a process, told apart from a red the
change caused.

a test that runs a command fails when the host cannot start that process:
an `OSError` with a WinError or errno code, raised at spawn, and nothing in
the code under test changes it. a gate that reads such a failure as the
change's red sends a correct step back, or stops the run on a question
nobody needs to answer. so a gate whose every red carries the same such
error runs once more, and a fault that holds is an issue: the gate could not
do its job, it does not send the step back, and it never asks for a ruling.

only `OSError` itself counts. its subclasses (`FileNotFoundError`,
`PermissionError` and the rest) are what wrong code raises too, and so is
any other exception. and a bare `OSError` is the host's only when it came
from starting a process: its code is one a spawn raises (`SPAWN`), or its
traceback shows the spawn. code that removes a full folder, renames across
drives or passes a bad argument raises a bare `OSError` too, and that red
is the change's.
"""
import re

FAULT = re.compile(r"(?<![\w.])OSError\b:?\s*\(?['\"]?\[(?:WinError|Errno) "
                   r"(\d+)\][^\n]*")
SUMMARY = re.compile(r"^=+ short test summary info =+$")
RED = re.compile(r"^(?:FAILED|ERROR) \S+(?: - (.*))?$")
# the codes a host raises when it cannot start a process: a bad parameter,
# not an executable, not found, an argument list too long, an exec format
# error, no memory
SPAWN = ("WinError 87", "WinError 193", "WinError 2", "Errno 7", "Errno 8",
         "Errno 12")
SPAWNED = re.compile(r"[\\/]subprocess\.py\b|\b_execute_child\b"
                     r"|\bCreateProcess\b")
SECTION = re.compile(r"^_{3,} .+ _{3,}$", re.M)


def found(said, spawned=False):
    """-> (the fault's match, its code) in `said` when it is the host's:
    a spawn's code, or any code with the spawn shown, by `said` itself or,
    when `spawned`, by the traceback it came with. None otherwise."""
    m = FAULT.search(said or "")
    if not m:
        return None
    code = ("WinError " if "WinError" in m.group(0) else "Errno ") \
        + m.group(1)
    if code in SPAWN or spawned or SPAWNED.search(said):
        return m, code
    return None


def key(said, spawned=False):
    """-> the host's fault's code in `said`, "" when it names none."""
    f = found(said, spawned)
    return f[1] if f else ""


def line(said, spawned=False):
    """-> the host's fault as `said` words it, "" when it names none."""
    f = found(said, spawned)
    return f[0].group(0).strip() if f else ""


def same(said, spawned=False):
    """-> the fault every one of `said` names, the first one's words, when
    there is at least one and they all name the same code; "" otherwise."""
    said = list(said)
    if not said:
        return ""
    keys = set(key(s, spawned) for s in said)
    if len(keys) != 1 or "" in keys:
        return ""
    return line(said[0], spawned)


def reds(output):
    """-> what each failed or errored test said, read off a pytest run's
    short summary."""
    out = []
    seen = False
    for text in (output or "").splitlines():
        if SUMMARY.match(text.strip()):
            seen = True
            continue
        m = RED.match(text.strip()) if seen else None
        if m:
            out.append(m.group(1) or "")
    return out


def of_run(output):
    """-> the fault on every red of a pytest run, "" when there is none or
    a red is anything else. a code no spawn raises counts only when every
    failure the run printed shows the spawn in its traceback."""
    traces = SECTION.split(output or "")[1:]
    return same(reds(output), bool(traces) and all(
        SPAWNED.search(t) for t in traces))


def named(e):
    """-> an error raised starting a process, in words `line` can read: a
    bare `OSError` says it is one, and where it was raised when that was
    the spawn; anything else is said as it was."""
    if type(e) is not OSError:
        return str(e)
    tb, spawn = e.__traceback__, ""
    while tb is not None:
        if tb.tb_frame.f_code.co_name == "_execute_child":
            spawn = " (in subprocess._execute_child)"
        tb = tb.tb_next
    return "OSError: " + str(e) + spawn


def held(r, what, fault):
    """`r`, a failed gate's result, marked as one the host's `fault` held
    twice: it could not `what`, and the step is not sent back for it."""
    r.ok = False
    r.broke = True
    r.issue = "could not " + what + ": " + fault
    r.host = fault
    return r
