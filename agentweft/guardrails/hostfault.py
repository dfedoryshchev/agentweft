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
any other exception.
"""
import re

FAULT = re.compile(r"(?<![\w.])OSError\b:?\s*\(?['\"]?\[(?:WinError|Errno) "
                   r"(\d+)\][^\n]*")
SUMMARY = re.compile(r"^=+ short test summary info =+$")
RED = re.compile(r"^(?:FAILED|ERROR) \S+(?: - (.*))?$")


def key(said):
    """-> the fault's code in `said`, "" when it names none."""
    m = FAULT.search(said or "")
    return ("WinError " if "WinError" in m.group(0) else "Errno ") \
        + m.group(1) if m else ""


def line(said):
    """-> the fault as `said` words it, "" when it names none."""
    m = FAULT.search(said or "")
    return m.group(0).strip() if m else ""


def same(said):
    """-> the fault every one of `said` names, the first one's words, when
    there is at least one and they all name the same code; "" otherwise."""
    said = list(said)
    if not said:
        return ""
    keys = set(key(s) for s in said)
    if len(keys) != 1 or "" in keys:
        return ""
    return line(said[0])


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
    a red is anything else."""
    return same(reds(output))


def named(e):
    """-> an error raised starting a process, in words `line` can read: a
    bare `OSError` says it is one, anything else is said as it was."""
    return ("OSError: " + str(e)) if type(e) is OSError else str(e)


def held(r, what, fault):
    """`r`, a failed gate's result, marked as one the host's `fault` held
    twice: it could not `what`, and the step is not sent back for it."""
    r.ok = False
    r.broke = True
    r.issue = "could not " + what + ": " + fault
    r.host = fault
    return r
