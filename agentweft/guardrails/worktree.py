"""a second checkout of the repo, for running something on another state of it.

`git worktree add --detach` into a temp folder, removed in a `finally`. the
person's own checkout is never stashed, checked out or reset to get there: a
stash rewrites the time of every file it touches, and a checkout in a tree
with work in it can lose that work. the repo's own hooks are not run for it:
a post-checkout hook is the repo's code, run by nobody's choice.

the checkout is locked while it exists, with the pid of the run that made it
as the reason. a run killed while one exists leaves it behind, registered in
the repo, and the folder on disk. the next run's start removes every one this
module made (they are named by PREFIX) whose run is no longer alive, and no
other: one locked by a live run, or locked by a person, is left alone.
"""
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePath

PREFIX = "agentweft-replay-"
REASON = "agentweft pid "


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root)] + list(args),
                           capture_output=True, encoding="utf-8",
                           errors="replace")
    except OSError:
        raise ValueError("git is not on PATH")
    if r.returncode != 0:
        raise ValueError("git " + " ".join(a for a in args[:3]
                                           if not a.startswith("core."))
                         + ": " + (r.stderr or r.stdout).strip()[:200])
    return r.stdout


def alive(pid):
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # os.kill(pid, 0) on windows terminates the process instead of
        # asking whether it exists
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        got = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(got) and code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove(root, path):
    try:
        _git(root, "worktree", "unlock", str(path))
    except ValueError:
        pass
    try:
        _git(root, "worktree", "remove", "--force", str(path))
    except ValueError:
        if not Path(path).exists():
            try:
                _git(root, "worktree", "prune")
            except ValueError:
                pass
    shutil.rmtree(str(path), ignore_errors=True)


@contextmanager
def temporary(root, start):
    """-> the path of a checkout of `start`, detached, gone on the way out
    whatever happened inside."""
    path = tempfile.mkdtemp(prefix=PREFIX)
    hooks = tempfile.mkdtemp(prefix=PREFIX + "hooks-")
    try:
        _git(root, "-c", "core.hooksPath=" + hooks, "worktree", "add",
             "--detach", "--lock", "--reason", REASON + str(os.getpid()),
             path, start)
        yield Path(path)
    finally:
        remove(root, path)
        shutil.rmtree(hooks, ignore_errors=True)


def leftovers(place):
    """-> the checkouts this module made that are still registered in the
    repo `place` is in and that no live run holds, [] when it is in none."""
    try:
        out = _git(place, "worktree", "list", "--porcelain")
    except ValueError:
        return []
    found = []
    for entry in out.split("\n\n"):
        lines = entry.strip().split("\n")
        if not lines[0].startswith("worktree "):
            continue
        path = lines[0][len("worktree "):].strip()
        if not PurePath(path).name.startswith(PREFIX):
            continue
        locked = [l for l in lines if l == "locked" or l.startswith("locked ")]
        if locked:
            reason = locked[0][len("locked"):].strip()
            if not reason.startswith(REASON):
                continue
            try:
                pid = int(reason[len(REASON):])
            except ValueError:
                continue
            if alive(pid):
                continue
        found.append(path)
    return found


def prune(place):
    """remove what a killed run left behind. -> the paths removed."""
    gone = leftovers(place)
    for path in gone:
        remove(place, path)
    return gone
