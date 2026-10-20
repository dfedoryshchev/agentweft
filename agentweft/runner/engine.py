import os
import sys
import time
from pathlib import Path

from agentweft import providers
from agentweft.guardrails import signoff  # noqa: F401
from agentweft.mcp import context, preflight  # noqa: F401

from .config import config, steps  # noqa: F401
from .handoff import EMPTY  # noqa: F401
from . import errors
from .errors import Fatal, Outage, kind_of
from .settings import get as setting  # noqa: F401
from . import begin, loop
from . import warm
from . import worktrees
from .asking import lead_pass, rides, to_lead, worked_then_asked  # noqa: F401
from .begin import (Leg, caps_given, carried, first_reader,  # noqa: F401
                    new_run_id, valued)
from .ending import (CAPS, FLAG_OF, SEV, by_severity, cap_of,  # noqa: F401
                     finish, is_graded, items, journal, next_run_path, passes,
                     remember, resume_command, show, write_index)
from .fanout import fanned_verdict, run_fanout  # noqa: F401
from .gating import (NEWLINE, RED_MARKER, and_forged,  # noqa: F401
                     check_step, clocked, forged_by, forged_first, gate_told,
                     gate_why, held_after_stop, nothing_why, off_task,
                     outage_why, police_line, sent_back_times, shown, since,
                     times)
from .loop import completion, roles_of  # noqa: F401
from .once import run_once  # noqa: F401
from .run import Run, replays  # noqa: F401

HERE = Path(__file__).resolve().parent


def load_env():
    # not worth a dependency for six lines
    if not os.path.exists(".env"):
        return
    for line in open(".env", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        os.environ[k] = v


def console():
    """output piped to a file or a program is UTF-8; on a terminal a
    character the console has no byte for is printed as `?`.

    a model answers in any script and a Windows console is often cp1252, so
    printing an answer raised after the run's work was done and written down.
    a PYTHONIOENCODING the person set is kept.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty() or os.environ.get("PYTHONIOENCODING"):
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def retry(fn, cap=3, sleep=time.sleep):
    tries = 0
    wait = 2
    while tries < cap:
        ok, out = fn()
        if ok:
            return out
        tries = tries + 1
        if tries < cap:
            print("cli failed, waiting " + str(wait) + "s")
            sleep(wait)
            wait = wait * 2
    print("giving up")
    return ""


class Answer(tuple):
    """(text, cached), the pair call has always handed back, plus every reply
    it took to get there and how many goes failed, by cause."""

    def __new__(cls, text, cached, replies=(), retries=None):
        self = tuple.__new__(cls, (text, cached))
        self.replies = list(replies)
        self.retries = retries or {}
        return self


def call(prompt, timeout=None, cap=3, step="?", provider=None):
    p = provider or providers.build({})
    heard = []
    failed = {}

    def once():
        reply = p.ask(prompt, timeout=timeout)
        heard.append(reply)
        if reply:
            return True, reply.text
        kind = kind_of(reply)
        print("step " + step + " failed (" + kind.__name__.lower() + "): "
              + reply.detail)
        cause = kind.__name__.lower()
        failed[cause] = failed.get(cause, 0) + 1
        if kind is Fatal:
            # going again will not help and it still costs
            raise Fatal(reply.detail, replies=heard, retries=failed)
        if kind is Outage:
            raise Outage(reply.detail,
                         reply.outage or errors.resets(reply.detail),
                         replies=heard, retries=failed)
        return False, reply.text

    answer = retry(once, cap)
    return Answer(answer, False, heard, failed)


def main():
    unrecorded = []
    try:
        return run_flow(unrecorded)
    except BaseException:
        # a checkout made before the run's record names it is in no list
        # and under a name prune skips, so nothing would ever remove it
        for made in unrecorded:
            worktrees.discard(made)
        raise
    finally:
        warm.stop_all()


def run_flow(unrecorded):
    console()
    if len(sys.argv) < 2:
        from .cli import cmd_help

        return cmd_help()
    load_env()
    leg = begin.begin(unrecorded)
    if not isinstance(leg, Leg):
        return leg
    return loop.go(leg)


if __name__ == "__main__":
    sys.exit(main())
