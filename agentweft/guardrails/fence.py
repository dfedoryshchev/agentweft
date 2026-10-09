"""the scope fence: what a step may not touch is what nobody can put back.

the rule is recoverability, not permission. a file git tracks can be restored
from git, and a file this run created did not exist before it, so a step is
free to touch both. a file that was in the place before the run and that git
does not track - a `.env`, a local fixture, work nobody has committed yet - has
no copy anywhere, and a step that changes, removes or adds one to git parks the
run for a person.

it works at the boundary and nowhere else. the run lists what git does not
track in the place when it starts, ignored files included, and after every
step it asks `git status` again and compares. nothing here is in the path of
the model's tool calls.

this catches mistakes, not a determined agent with a shell. a step that means
to can write outside the place, into a path the fence skips, or put a file's
size and time back after changing it. it is not a security boundary.
"""
import hashlib
import os
import subprocess
from pathlib import Path

import yaml

from agentweft.orchestrate import project

LOOSE = ("??", "!!")


def _git(place, *args):
    try:
        r = subprocess.run(["git", "-C", str(place)] + list(args),
                           capture_output=True, encoding="utf-8")
    except FileNotFoundError:
        raise ValueError("a fence needs git, and git is not on PATH")
    if r.returncode != 0:
        raise ValueError(str(place) + " is not in a git work tree, so nothing "
                         "tells a file git can restore from one it cannot")
    return r.stdout


def _stat(p):
    s = os.lstat(p)
    return s.st_size, s.st_mtime_ns


def _sha(p):
    try:
        if os.path.islink(p):
            return hashlib.sha256(os.readlink(p).encode("utf-8")).hexdigest()
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unreadable"


class Fence(object):
    """the untracked files in one place, as they were when the run started."""

    __slots__ = ("place", "root", "skip", "before")

    def __init__(self, place, skip=(), own=None):
        self.place = Path(place).resolve()
        self.root = Path(_git(self.place, "rev-parse", "--show-toplevel")
                         .strip()).resolve()
        self.skip = [":(exclude,glob)" + s for s in skip]
        if own is not None:
            try:
                rel = Path(own).resolve().relative_to(self.place).as_posix()
                self.skip.append(":(exclude,glob)" + rel + "/**")
            except ValueError:
                pass
        self.before = {}
        for rel in self.loose():
            p = self.root / rel
            try:
                self.before[rel] = (_stat(p), _sha(p))
            except OSError:
                continue

    def loose(self):
        """-> the paths git does not track under the place, relative to the
        top of the repo, the way `git status` prints them."""
        out = _git(self.place, "status", "--porcelain", "-z",
                   "--untracked-files=all", "--ignored", "--", ".", *self.skip)
        found = []
        fields = iter(out.split("\0"))
        for entry in fields:
            if not entry:
                continue
            code, rel = entry[:2], entry[3:]
            if code in LOOSE:
                found.append(rel)
            elif "R" in code or "C" in code:
                # -z gives a rename's old path a field of its own. read as an
                # entry, its first two letters would pass for a status code.
                next(fields, None)
        return found

    def crossed(self):
        """-> [(path, what happened to it)] for every file that was here
        untracked at the start and is not as it was, sorted by path."""
        now = set(self.loose())
        out = []
        for rel, (seen, digest) in sorted(self.before.items()):
            p = self.root / rel
            if not (p.exists() or p.is_symlink()):
                out.append((rel, "removed"))
            elif rel not in now:
                out.append((rel, "now tracked"))
            elif _stat(p) != seen and _sha(p) != digest:
                out.append((rel, "changed"))
        return out


def at(place, own=None):
    """-> the Fence project.yml declares, taken of `place` now, or None when
    there is no project.yml or it declares no fence."""
    if not project.path().exists():
        return None
    try:
        skip = project.read().fence()
    except yaml.YAMLError as e:
        raise ValueError("project.yml: " + str(e))
    if skip is None:
        return None
    return Fence(place, skip, own=own)
