"""a run that commits as it goes, or never commits at all.

`commits:` in flow.yaml says which. `none`, the default, never commits: some
repos must never get a commit nobody typed, and every gate works from the
start snapshot's content hashes without one. `wip` commits after each step
on a branch of the run's own, agentweft/<run id>, with a message naming the
step. `squash` does the same and, once every step has passed, folds the step
commits into one for the task.

the commits are evidence on top, never instead. the order of the commits is
the order the work was done in, and a commit's files are what its step
changed, so the handoff says which commit first held tests and which first
held product code. no verdict reads them, which is what keeps a run's verdict
the same with commits and without.

a commit holds what the run changed and nothing else: a file that was
already loose when the run started (a `.env`, a note nobody committed, a
change already staged) stays out while its bytes are what they were. the run
never commits on the branch it was started on and never pushes. the author
and the committer are whoever git config names in the place, and with no
user.name or user.email there the run refuses before its first step.
"""
import json
import subprocess
from pathlib import Path

from agentweft.guardrails.snapshot import _read, is_spec, is_test, is_tooling

from . import settings

NONE, WIP, SQUASH = "none", "wip", "squash"
MODES = (NONE, WIP, SQUASH)
FILE = "commits.json"
BRANCH = "agentweft/"


def mode(fm):
    """-> the flow's commit mode, `none` when it names none."""
    return settings.get("commits", flow=fm) or NONE


def _git(where, *args, given=None):
    try:
        r = subprocess.run(["git", "-C", str(where)] + list(args),
                           input=given, capture_output=True,
                           encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return 127, "", "git is not on PATH"
    return r.returncode, r.stdout, r.stderr


def load(folder):
    """-> what a run kept of its commits in `folder`, or None."""
    try:
        return json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Committer(object):
    """the commits of one run. with `none` every method does nothing."""

    def __init__(self, how, start, prior=None):
        self.how = how
        self.start = start
        self.branch = None
        self.base = None
        self.was = None
        self.made = []
        self.squashed = None
        self.order = None
        self.folder = None
        if how == NONE:
            return
        said = "commits: " + how
        if start is None or not start.ingit:
            raise ValueError(said + " needs a git work tree to commit in, and"
                             " the place is not in one")
        if not start.start:
            raise ValueError(said + " needs a commit to branch from, and the"
                             " repo has none")
        missing = [key for key in ("user.name", "user.email")
                   if not self._config(key)]
        if missing:
            raise ValueError(said + " authors the run's commits as the git"
                             " config's user.name and user.email, and the"
                             " place has no " + " and no ".join(missing)
                             + ". set it with git config, or run with"
                             " commits: none")
        if prior and prior.get("branch"):
            self.branch = prior["branch"]
            self.base = prior.get("base")
            self.was = prior.get("was")
            self.made = list(prior.get("made") or [])
            on = self.current()
            if on != self.branch:
                raise ValueError("the run's commits are on " + self.branch
                                 + " and the place is on "
                                 + (on or "no branch")
                                 + ". switch back to " + self.branch
                                 + " to carry the run on")

    def _config(self, key, kind=None):
        typed = ["--type=" + kind] if kind else []
        code, out, _ = _git(self.start.root, "config", *typed, "--get", key)
        return out.strip() if code == 0 else ""

    def current(self):
        code, out, _ = _git(self.start.root, "symbolic-ref", "--quiet",
                            "--short", "HEAD")
        return out.strip() if code == 0 else None

    def head(self):
        code, out, _ = _git(self.start.root, "rev-parse", "HEAD")
        return out.strip() if code == 0 else None

    def begin(self, run_id):
        """put the place on the run's own branch, before the first step. a
        run carried on stays on the branch it started."""
        if self.how == NONE or self.branch:
            return
        self.was = self.current()
        self.base = self.head()
        name = BRANCH + run_id
        code, _, err = _git(self.start.root, "checkout", "-q", "-b", name)
        if code != 0:
            raise ValueError("commits: " + self.how + " could not start the"
                             " run's branch " + name + ": " + err.strip())
        self.branch = name

    def keep_in(self, folder):
        self.folder = Path(folder)
        self.save()

    def save(self):
        if self.how == NONE or self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / FILE).write_text(json.dumps({
            "mode": self.how, "branch": self.branch, "base": self.base,
            "was": self.was, "made": self.made, "squashed": self.squashed},
            indent=1, sort_keys=True), encoding="utf-8")

    def pending(self):
        """-> the paths from the top of the repo the run has changed and not
        committed: what git sees as changed, less what was loose at the start
        and still has the bytes it had."""
        out = []
        for rel in self.start._dirty():
            if rel in self.start.loose and \
                    _read(self.start.root / rel) == self.start.loose[rel]:
                continue
            if rel not in out:
                out.append(rel)
        return out

    def _commit(self, paths, message):
        listed = "\0".join(paths) + "\0"
        code, _, err = _git(self.start.root, "add", "-A",
                            "--pathspec-from-file=-", "--pathspec-file-nul",
                            given=listed)
        if code != 0:
            raise ValueError("commits: git add failed: " + err.strip())
        code, out, _ = _git(self.start.root, "diff", "--cached",
                            "--name-only", "-z", "HEAD")
        if not set(out.split("\0")) & set(paths):
            return None
        # --only, so a change the person had staged before the run stays
        # staged and out of the run's commit; --no-verify, so a hook of the
        # repo's cannot fail a step whose gates passed
        code, _, err = _git(self.start.root, "commit", "-q", "--no-verify",
                            "--only", "--pathspec-from-file=-",
                            "--pathspec-file-nul", "-m", message,
                            given=listed)
        if code != 0:
            raise ValueError("commits: git commit failed: " + err.strip())
        return self.head()

    def step(self, name, flow):
        """commit what `name` changed. -> the sha, or None when nothing."""
        if self.how == NONE:
            return None
        paths = self.pending()
        if not paths:
            return None
        sha = self._commit(paths, "wip(" + flow + "): " + name)
        if sha:
            self.made.append({"step": name, "sha": sha, "files": paths})
            self.save()
        return sha

    def finish(self, flow, task, proved=()):
        """the end of a run every step of which passed: read the order off the
        commits, then, under `squash`, fold them into one for the task.
        `proved` is the red proof's test files, as paths from the place."""
        if self.how == NONE:
            return
        self.order = self.evidence([
            (self.start.place / f).relative_to(self.start.root).as_posix()
            for f in proved])
        if self.how != SQUASH or not self.base:
            return
        tip = self.head()
        code, tree, _ = _git(self.start.root, "rev-parse", "HEAD^{tree}")
        code_base, was, _ = _git(self.start.root, "rev-parse",
                                 self.base + "^{tree}")
        if code or code_base or tree.strip() == was.strip():
            return
        first = (task or "").strip().split("\n")[0][:60]
        message = flow + (": " + first if first else ": " + self.branch)
        body = "from the step commits:\n" + "\n".join(
            "- " + m["sha"][:12] + " " + m["step"] for m in self.made)
        # the tip's tree as it is, so a rename keeps no trace of the old
        # path, and the person's index and files are not touched
        sign = ["-S"] if self._config("commit.gpgsign", "bool") == "true" \
            else []
        code, sha, err = _git(self.start.root, "commit-tree", *sign,
                              tree.strip(), "-p", self.base,
                              given=message + "\n\n" + body + "\n")
        if code != 0:
            raise ValueError("commits: could not squash: " + err.strip())
        code, _, err = _git(self.start.root, "update-ref", "-m",
                            "agentweft: squash", "refs/heads/" + self.branch,
                            sha.strip(), tip)
        if code != 0:
            raise ValueError("commits: could not squash: " + err.strip())
        self.squashed = sha.strip()
        self.save()

    def evidence(self, tests=()):
        """-> what the commits since the base say about the order: the first
        commit holding a test file (one of `tests` when there are any) and the
        first holding product code, "" when there is nothing to say."""
        code, out, _ = _git(self.start.root, "rev-list", "--reverse",
                            self.base + "..HEAD")
        if code != 0:
            return ""
        wanted = set(tests)
        first_test = first_product = None
        for sha in out.split():
            code, files, _ = _git(self.start.root, "diff-tree",
                                  "--no-commit-id", "--name-only", "-r", "-z",
                                  sha)
            for rel in (f for f in files.split("\0") if f):
                if is_test(rel):
                    if first_test is None and (not wanted or rel in wanted):
                        first_test = sha
                elif first_product is None and not is_tooling(rel) \
                        and not self._spec(rel):
                    first_product = sha
        if not first_product:
            return ""
        if not first_test:
            return ("product code first in " + first_product[:12]
                    + ", no tests committed")
        if first_test == first_product:
            return ("tests and the first product code in the same commit, "
                    + first_test[:12])
        if out.split().index(first_test) < out.split().index(first_product):
            return ("tests in " + first_test[:12] + " before the first product"
                    " code in " + first_product[:12])
        return ("product code in " + first_product[:12] + " before the tests"
                " in " + first_test[:12])

    def _spec(self, rel):
        try:
            return is_spec(self.start.from_place(rel))
        except ValueError:
            return False

    def said(self):
        """-> the handoff's line on the commits, "" under `none`."""
        if self.how == NONE or not self.branch:
            return ""
        order = self.order if self.order is not None else self.evidence()
        steps = ", ".join(m["step"] + " " + m["sha"][:12] for m in self.made)
        if self.squashed:
            line = ("squashed into " + self.squashed[:12] + " on "
                    + self.branch + " from " + str(len(self.made))
                    + " step commit" + ("" if len(self.made) == 1 else "s"))
        else:
            line = (self.how + " on " + self.branch + ": "
                    + (steps or "nothing committed"))
        if self.was:
            line = line + ", started from " + self.was
        return line + ("; " + order if order else "")
