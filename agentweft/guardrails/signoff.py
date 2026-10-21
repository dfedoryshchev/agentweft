"""the sign-off: a run that changed files ends by asking git whether its change
still merges onto the branch it is for, as that branch is now.

the branch is the one named with `--target`. without it, a run in a worktree
of its own is for the branch checked out in the person's tree, which moves
while the person works; any other run is for the upstream of the branch
checked out (the branch itself cannot move without HEAD moving with it). its
head is read when the run starts, again before each step (`ahead`) and again
when it ends. not moved, nothing more is said. moved, the run's change (HEAD now, with every file the tree
holds that differs from what it held at the start) is merged onto the new
head with `git merge-tree`, and a conflict stops the run naming the files. a
file that was already loose at the start and that the run left as it was is
the person's, not the run's, and stays out.

read only. the merge is built with an index and an object folder of its own in
a temporary folder, the repo's objects read through an alternate, and the
folder is removed after: the person's tree, index, HEAD, branches and object
store are as they were, and nothing is staged or committed in them. a check
that needs more than that (a branch that cannot be read, a git without
`merge-tree --write-tree`) is not done: the run stops and says what to check
by hand.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

SAME = "same"
MERGES = "merges"
CONFLICT = "conflict"
UNCHECKED = "unchecked"
NOTHING = "nothing to check"

WHO = {"GIT_AUTHOR_NAME": "agentweft", "GIT_AUTHOR_EMAIL": "agentweft@local",
       "GIT_COMMITTER_NAME": "agentweft",
       "GIT_COMMITTER_EMAIL": "agentweft@local"}


def _git(place, *args, env=None, stdin=None):
    """-> (exit code, stdout, stderr); exit None when git is not there."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(place)]
                           + list(args), capture_output=True, input=stdin,
                           env=env)
    except OSError as e:
        return None, "", str(e)
    return (r.returncode, r.stdout.decode("utf-8", "replace"),
            r.stderr.decode("utf-8", "replace"))


def _out(place, *args):
    code, out, _ = _git(place, *args)
    return out.strip() if code == 0 else None


def _commit(place, ref):
    return _out(place, "rev-parse", "--verify", "--quiet", ref + "^{commit}")


def _branch(place):
    return _out(place, "symbolic-ref", "--short", "-q", "HEAD")


def _upstream(place, branch):
    return _out(place, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                branch + "@{upstream}")


def _bytes(root, rel):
    try:
        with open(os.path.join(str(root), rel), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def mark(place, target=None, origin=None):
    """-> what the run starts from: {"target", "head", "base", "branch",
    "loose"}, or None when the place is not in a git work tree with a
    commit. `origin` is the person's own tree, for a run in a worktree of its
    own."""
    root = _out(place, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    base = _commit(place, "HEAD")
    if base is None:
        return None
    branch = _branch(origin or place)
    if not target and branch:
        target = branch if origin else _upstream(place, branch)
    loose = changed(root) or []
    return {"target": target or None,
            "head": _commit(place, target) if target else None,
            "base": base, "branch": branch,
            "loose": dict((rel, _bytes(root, rel)) for rel in loose)}


class Signed(object):
    __slots__ = ("state", "target", "head", "files", "why")

    def __init__(self, state, target=None, head=None, files=(), why=""):
        self.state = state
        self.target = target
        self.head = head
        self.files = list(files)
        self.why = why

    def lines(self):
        """-> what the handoff says of it under its checks."""
        if self.state == MERGES:
            return ["- sign-off: " + self.target + " moved to " + self.head
                    + " since the run started; the change was re-checked on"
                    " it and merges with no conflict"]
        if self.state == NOTHING and self.why:
            return ["- sign-off: not checked, " + self.why]
        return []


def changed(root):
    """-> the paths the tree has that HEAD does not, from the top of the
    repo, or None when git could not say."""
    code, tracked, _ = _git(root, "diff", "--name-only", "-z", "HEAD")
    more, loose, _ = _git(root, "ls-files", "-z", "--others",
                          "--exclude-standard")
    if code != 0 or more != 0:
        return None
    return sorted(set(p for p in (tracked + loose).split("\0") if p))


def filtered(root, paths):
    """-> the first of `paths` git hands to a filter program (an lfs, say)
    when it reads the file, as (path, filter), () for none, or None when git
    could not say. the program is not git and may write where it likes."""
    code, out, _ = _git(root, "check-attr", "-z", "--stdin", "filter",
                        stdin="\0".join(paths).encode("utf-8"))
    if code != 0:
        return None
    said = out.split("\0")
    for i in range(0, len(said) - 2, 3):
        if said[i + 2] not in ("unspecified", "unset"):
            return said[i], said[i + 2]
    return ()


def merged(root, paths, theirs):
    """-> (exit code of merge-tree, its output, what failed) for HEAD with
    `paths` from the tree on top, merged onto `theirs`. everything it writes
    goes into a temporary folder that is removed before it returns."""
    objects = _out(root, "rev-parse", "--git-path", "objects")
    if objects is None:
        return None, "", "git rev-parse --git-path objects failed"
    room = tempfile.mkdtemp(prefix="agentweft-signoff-")
    try:
        env = dict(os.environ, **WHO)
        env.update({"GIT_INDEX_FILE": os.path.join(room, "index"),
                    "GIT_OBJECT_DIRECTORY": os.path.join(room, "objects"),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES":
                        str((Path(root) / objects).resolve())})
        os.mkdir(os.path.join(room, "objects"))
        steps = [(("read-tree", "HEAD"), None),
                 (("update-index", "--add", "--remove", "-z", "--stdin"),
                  "\0".join(paths).encode("utf-8")),
                 (("write-tree",), None)]
        out = ""
        for args, stdin in steps:
            code, out, err = _git(root, *args, env=env, stdin=stdin)
            if code != 0:
                return None, "", "git " + args[0] + ": " + err.strip()[:200]
        code, out, err = _git(root, "-c", "commit.gpgsign=false",
                              "commit-tree", out.strip(), "-p", "HEAD", "-m",
                              "sign-off check", env=env)
        if code != 0:
            return None, "", "git commit-tree: " + err.strip()[:200]
        code, out, err = _git(root, "merge-tree", "--write-tree",
                              "--name-only", "--no-messages", out.strip(),
                              theirs, env=env)
        if code not in (0, 1):
            return None, "", "git merge-tree: " + err.strip()[:200]
        return code, out, ""
    finally:
        shutil.rmtree(room, ignore_errors=True)


def by_hand(target, why):
    return Signed(UNCHECKED, target, why=(
        "the change could not be checked against " + target + " with"
        " read-only git (" + why + "). check by hand that it merges onto "
        + target + ", for one with git merge-tree --write-tree HEAD "
        + target + " once the change is committed"))


def runs_own(root, start):
    """-> the paths the run changed: those that differ from HEAD now, but
    for a file loose at the start that still holds the bytes it held then.
    None when git could not say."""
    paths = changed(root)
    if paths is None:
        return None
    loose = start.get("loose") or {}
    return [p for p in paths
            if p not in loose or _bytes(root, p) != loose[p]]


def unpointed(start):
    if start.get("branch"):
        return start["branch"] + " has no upstream and no --target was named"
    return "HEAD was detached when the run started and no --target was named"


def ahead(place, start, seen, step):
    """the check before `step`: -> (a Signed, the target's head it was made
    on) when the target's head is not `seen`, the head the last check found
    (the run's start, first), else (None, `seen`). a target that did not
    move costs one rev-parse; one that moved is merged as at the end. no
    target, nothing is checked here: the end says so."""
    target = (start or {}).get("target")
    if not target:
        return None, seen
    now = _commit(place, target)
    if now is not None and now == seen:
        return None, seen
    return check(place, start, "before " + step), now


def check(place, start, when="at the end of the run"):
    """-> a Signed for the run that started at `start` (`mark`)."""
    if not start:
        return Signed(NOTHING)
    target = start.get("target")
    root = _out(place, "rev-parse", "--show-toplevel")
    if root is None:
        if target:
            return by_hand(target, "git could not read " + str(place)
                           + " " + when)
        return Signed(NOTHING)
    if not target:
        paths = runs_own(root, start)
        if not paths and _commit(root, "HEAD") == start.get("base"):
            return Signed(NOTHING)
        return Signed(NOTHING, why=unpointed(start))
    now = _commit(root, target)
    if now is None:
        return by_hand(target, target + " cannot be read now")
    if now == start.get("head") or now == _commit(root, "HEAD"):
        return Signed(SAME, target, now)
    paths = runs_own(root, start)
    if paths is None:
        return by_hand(target, "git could not list what the run changed")
    if not paths and _commit(root, "HEAD") == start.get("base"):
        return Signed(NOTHING, target, now)
    hit = filtered(root, paths)
    if hit is None:
        return by_hand(target, "git check-attr could not say which files go"
                       " through a filter program")
    if hit:
        return by_hand(target, hit[0] + " is read through the " + hit[1]
                       + " filter, a program outside git")
    code, out, why = merged(root, paths, now)
    if code is None:
        return by_hand(target, why)
    if code == 0:
        return Signed(MERGES, target, now)
    files = sorted(set(l for l in out.split("\n")[1:] if l.strip()))
    return Signed(CONFLICT, target, now, files, why=(
        target + " moved to " + now + " since the run started, and the"
        " change conflicts with it in " + ", ".join(files) + ". rebase onto "
        + target + " (" + now + ") and settle " + ", ".join(files)
        + ", then carry on"))
