"""a fanned step's tasks, read off the plan, and what each one wrote.

a task is a block of the plan, one item per line:

    TASK: <what to do>
    FILES:
    - <a file it touches>
    - <another>

it runs to the next TASK: line or the first blank line; a FILES list after a
blank line still belongs to the task above it when that task has none. the
worker is handed the block as it is. a task that touches no file has an empty
FILES list. a path is compared as the place would spell it: `src/../a.py` is
`a.py`, and on windows and macos `A.py` is `a.py`.

the tasks run in one place, so two that name the same file run one after
another, in plan order. after the fan, `check` reads what changed while each
task ran: a file a task wrote without naming it, one two tasks wrote, or one
that changed while two tasks ran side by side and one of them did not name it
(the hashes cannot say which wrote it), is named with the tasks.
"""
import hashlib
import json
import os
import posixpath
import subprocess
import sys
from pathlib import Path

TASK = "TASK:"
FILES = "FILES:"
SKIP_DIRS = ("__pycache__", "node_modules", "venv", ".venv")
FOLD = os.name == "nt" or sys.platform == "darwin"
FILE = "fan-start.json"


class Task(object):
    __slots__ = ("n", "text", "files")

    def __init__(self, n, text, files):
        self.n = n
        self.text = text
        self.files = tuple(files)

    def names(self, path):
        return key(path) in set(key(f) for f in self.files)

    def __repr__(self):
        return "Task(" + str(self.n) + ", " + repr(self.files) + ")"


def path_of(said):
    path = said.strip().strip("`").replace(chr(92), "/")
    return posixpath.normpath(path) if path else path


def key(path):
    """-> `path` as two spellings of one file compare."""
    path = path_of(path)
    return path.lower() if FOLD else path


def tasks(text):
    """-> every task in `text`, in plan order."""
    out = []
    lines, files, listing = None, [], False
    for line in (text or "").split("\n") + [""]:
        bare = line.strip()
        if bare.startswith(TASK) or not bare:
            if lines:
                out.append(Task(len(out) + 1, "\n".join(lines), files))
            lines, files, listing = None, [], False
            if bare:
                lines = [bare]
            continue
        if lines is None:
            if bare != FILES or not out or out[-1].files:
                continue
            lines = out.pop().text.split("\n")
        lines.append(bare)
        if bare == FILES:
            listing = True
        elif listing and bare.startswith("- "):
            files.append(path_of(bare[2:]))
        else:
            listing = False
    return out


def turns(found):
    """-> the tasks in runs: tasks whose files overlap, even through a third
    task, share a run and go one after another in plan order. runs share no
    file, so they can go side by side."""
    runs = []
    for t in found:
        mine = set(key(f) for f in t.files)
        joined = [r for r in runs
                  if mine & set(key(f) for x in r for f in x.files)]
        merged = [x for r in joined for x in r] + [t]
        runs = [r for r in runs if r not in joined]
        runs.append(sorted(merged, key=lambda x: x.n))
    return sorted(runs, key=lambda r: r[0].n)


def _sha(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _listed(place):
    try:
        r = subprocess.run(["git", "-C", str(place), "ls-files", "-z",
                            "--cached", "--others", "--exclude-standard"],
                           capture_output=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


def hashes(place, own=None):
    """-> {path from the place: sha256} for every file in it, git's ignored
    files, the run's own folder and bytecode left out."""
    place = Path(place)
    mine = None
    if own is not None:
        try:
            mine = Path(own).resolve().relative_to(place.resolve()) \
                .as_posix() + "/"
        except ValueError:
            mine = None
    found = _listed(place)
    if found is None:
        found = []
        for top, dirs, names in os.walk(str(place)):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d not in SKIP_DIRS]
            found.extend(Path(top, n).relative_to(place).as_posix()
                         for n in names)
    out = {}
    for rel in found:
        if (mine and rel.startswith(mine)) or "__pycache__" in rel \
                or rel.endswith(".pyc"):
            continue
        sha = _sha(place / rel)
        if sha is not None:
            out[rel] = sha
    return out


def changed(before, after):
    return set(p for p in set(before) | set(after)
               if before.get(p) != after.get(p))


class Window(object):
    """what the place held when a task started and when it ended."""

    __slots__ = ("task", "began", "ended", "before", "after")

    def __init__(self, task, began, before):
        self.task = task
        self.began = began
        self.before = before
        self.ended = None
        self.after = None

    def changed(self):
        return changed(self.before, self.after)

    def beside(self, other):
        return other is not self and self.began < other.ended \
            and other.began < self.ended


def _tasks(ns):
    names = ["task " + str(n) for n in sorted(ns)]
    return names[0] if len(names) == 1 else \
        ", ".join(names[:-1]) + " and " + names[-1]


def check(windows):
    """-> "" when every task wrote only what it named and no file was
    written by two, else what was not."""
    wrote, stray, seen = {}, {}, {}
    for w in windows:
        for path in w.changed():
            seen.setdefault(path, set()).add(w.task.n)
            if w.task.names(path):
                wrote.setdefault(path, set()).add(w.task.n)
            else:
                stray.setdefault(path, set()).add(w.task.n)
    by_n = dict((w.task.n, w) for w in windows)
    said = []
    for path in sorted(stray):
        alone = stray[path]
        with_it = set(n for n in seen[path] if any(
            by_n[n].beside(by_n[m]) for m in alone))
        if len(with_it | alone) == 1:
            said.append(_tasks(alone) + " wrote " + path
                        + ", which it did not name")
            continue
        who = ("neither" if len(alone) == 2 else "none of them") \
            if not with_it - alone else _tasks(alone)
        said.append(path + " changed while " + _tasks(with_it | alone)
                    + " ran side by side, and " + who + (
                        " named it" if who in ("neither", "none of them")
                        else " did not name it"))
    for path in sorted(wrote):
        if len(wrote[path]) > 1:
            said.append(path + " was written by " + _tasks(wrote[path]))
    return "; ".join(said)


def since(start, now, found, step):
    """-> what changed from `start` that no task in `found` names, for a fan
    carried on from a run that stopped in it."""
    left = sorted(p for p in changed(start, now)
                  if not any(t.names(p) for t in found))
    return "; ".join(p + " changed since " + step + " first started, and"
                     " no task named it" for p in left)


def save(folder, start):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / FILE).write_text(json.dumps(start, sort_keys=True),
                                     encoding="utf-8")


def load(folder):
    """-> the place as a fan that did not end clean found it, or None."""
    try:
        return json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def done(folder):
    try:
        (Path(folder) / FILE).unlink()
    except OSError:
        pass
