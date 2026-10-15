"""what the place held when the run started, kept by content.

a gate that has to know which tests the run wrote cannot ask git for it: a
step may commit, may not, or may leave its work half staged, and a flow that
commits nothing has no history to read. so the run writes down, as it starts,
the commit it started from, a sha256 of every test file under the place, and
the bytes of every file that already differed from that commit. after a step,
a test file whose content is not what it was is one the run wrote or changed.

content, never mtimes: a stash and pop rewrites the time of every file it
touches without changing a byte, and an editor can save a file unchanged.

it also hashes the spec files and every other file (the product), and the
run keeps it as runs/<id>/start-snapshot.json, so a run picked up later
compares against the place as it first started and not as it was left.
"""
import ast
import base64
import fnmatch
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

FILE = "start-snapshot.json"
SPEC = ("TASK.md", "SPEC*.md", "docs/spec*")
SKIP_DIRS = ("__pycache__", "node_modules")

TEST_PATH = re.compile(r"(^|/)(tests?|spec|__tests__)/|(^|/)test_[^/]*\.py$"
                       r"|_tests?\.py$|\.(test|spec)\.[cm]?[jt]sx?$"
                       r"|Tests?\.cs$")
# a file that is itself one test to run, for the languages whose test ids
# this module cannot read out of the source
TEST_MODULE = re.compile(r"^test_.*\.py$|_test\.py$")
WHOLE_FILE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.cs$|_test\.go$")


def is_test(path):
    if "__pycache__" in path or path.endswith(".pyc"):
        return False
    return TEST_PATH.search(path) is not None


def _git(place, *args, text=True):
    try:
        r = subprocess.run(["git", "-C", str(place)] + list(args),
                           capture_output=True, text=False)
    except (FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace") if text else r.stdout


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def test_ids(source, rel):
    """-> {test id: a dump of its code} for the pytest tests in `source`, or
    None when it does not parse. an id is `rel::name` or `rel::Class::name`,
    the form `pytest` takes on its command line."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    out = {}
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)

    def walk(body, prefix):
        for node in body:
            if isinstance(node, funcs) and node.name.startswith("test"):
                out[prefix + "::" + node.name] = ast.dump(node)
            elif isinstance(node, ast.ClassDef) and collected(node):
                walk(node.body, prefix + "::" + node.name)

    walk(tree.body, rel)
    return out


def collected(node):
    """whether pytest collects the class: named Test*, or a unittest case."""
    if node.name.startswith("Test"):
        return True
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else \
            getattr(base, "id", "")
        if name.endswith("TestCase"):
            return True
    return False


def is_spec(path):
    return not is_test(path) and any(fnmatch.fnmatchcase(path, g)
                                     for g in SPEC)


class Snapshot(object):
    """the place as the run found it. `why` says why there is no start to
    replay from ("" when there is): not a git work tree, or no commit.
    `hashed` says whether the files were hashed at all, which a place outside
    git still is: an order check needs content, not history."""

    __slots__ = ("place", "root", "start", "tests", "specs", "product",
                 "loose", "own", "why", "hashed", "ingit")

    def __init__(self, place, own=None, why=""):
        self.place = Path(place).resolve()
        self.root = None
        self.start = None
        self.tests = {}
        self.specs = {}
        self.product = {}
        self.loose = {}
        self.own = None
        self.why = ""
        self.hashed = False
        self.ingit = False
        if why:
            self.why = why
            return
        top = _git(self.place, "rev-parse", "--show-toplevel")
        if top is None:
            self.why = "the place is not in a git work tree"
            self.root = self.place
        else:
            self.root = Path(top.strip()).resolve()
            self.ingit = True
        if own is not None:
            try:
                self.own = Path(own).resolve().relative_to(self.root) \
                    .as_posix() + "/"
            except ValueError:
                self.own = None
        if top is not None:
            head = _git(self.place, "rev-parse", "--verify", "--quiet",
                        "HEAD")
            if head:
                self.start = head.strip()
            else:
                self.why = "the repo has no commit to start from"
        self.tests, self.specs, self.product = self.hashes()
        self.hashed = True
        if self.start:
            for rel in self._dirty():
                self.loose[rel] = _read(self.root / rel)

    def _mine(self, rel):
        return bool(self.own) and rel.startswith(self.own)

    def files(self):
        """-> every file under the place, tracked or not, ignored ones left
        out, as paths from the top of the repo. outside git, every file under
        the place but those in a folder whose name starts with a dot."""
        if not self.ingit:
            found = []
            for top, dirs, names in os.walk(str(self.place)):
                dirs[:] = [d for d in dirs
                           if not d.startswith(".") and d not in SKIP_DIRS]
                for name in names:
                    found.append(Path(top, name).relative_to(self.place)
                                 .as_posix())
        else:
            out = _git(self.place, "ls-files", "-z", "--full-name",
                       "--cached", "--others", "--exclude-standard", "--",
                       ".") or ""
            found = out.split("\0")
        seen = set()
        out = []
        for rel in found:
            if not rel or rel in seen or self._mine(rel) \
                    or "__pycache__" in rel or rel.endswith(".pyc"):
                continue
            seen.add(rel)
            out.append(rel)
        return sorted(out)

    def test_files(self):
        """-> the test files under the place, as paths from the top of the
        repo."""
        return [rel for rel in self.files() if is_test(rel)]

    def hashes(self):
        """-> ({test file: sha256}, {spec file: sha256}, {product file:
        sha256}) as the place is now. a product file is every file that is
        neither."""
        tests, specs, product = {}, {}, {}
        for rel in self.files():
            data = _read(self.root / rel)
            if data is None:
                continue
            kind = tests if is_test(rel) else specs if is_spec(rel) \
                else product
            kind[rel] = _sha(data)
        return tests, specs, product

    def product_now(self):
        return self.hashes()[2]

    def to_json(self):
        return {"place": str(self.place),
                "root": str(self.root) if self.root else None,
                "start": self.start, "own": self.own, "why": self.why,
                "hashed": self.hashed, "ingit": self.ingit, "tests": self.tests,
                "specs": self.specs, "product": self.product,
                "loose": dict((rel, None if data is None
                               else base64.b64encode(data).decode("ascii"))
                              for rel, data in self.loose.items())}

    def save(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / FILE).write_text(json.dumps(self.to_json(), indent=1,
                                                    sort_keys=True),
                                         encoding="utf-8")

    def _dirty(self):
        out = _git(self.place, "status", "--porcelain", "-z",
                   "--untracked-files=all", "--", ".") or ""
        found = []
        fields = iter(out.split("\0"))
        for entry in fields:
            if not entry:
                continue
            code, rel = entry[:2], entry[3:]
            if "R" in code or "C" in code:
                # -z gives a rename's old path a field of its own, and the old
                # path is as gone from the start state as a deletion
                old = next(fields, None)
                if old and not self._mine(old):
                    found.append(old)
            if not self._mine(rel):
                found.append(rel)
        return found

    def before(self, rel):
        """-> the bytes `rel` had when the run started, None when it was not
        there."""
        if rel in self.loose:
            return self.loose[rel]
        return _git(self.root, "show", self.start + ":" + rel, text=False)

    def test_changes(self):
        """-> [(path from the top of the repo, its bytes now)] for every test
        file under the place that is new since the start or not as it was."""
        if not self.hashed:
            return []
        out = []
        for rel in self.test_files():
            now = _read(self.root / rel)
            if now is not None and self.tests.get(rel) != _sha(now):
                out.append((rel, now))
        return out

    def from_place(self, rel):
        """a path from the top of the repo, as one from the place."""
        return (self.root / rel).relative_to(self.place).as_posix()

    def new_test_ids(self, changes=None):
        """-> the tests the run added or changed, as ids a test command takes
        from the place, in file order.

        a python test is new when its name was not in the file at the start
        or its code is not what it was. a python test module whose tests are
        not read here (made at import, or not parsing) is one id of its own,
        and so is a file in another language named like a test file; a
        support file (a fixture, a conftest) is a change and no id.
        """
        out = []
        for rel, now in (self.test_changes() if changes is None else changes):
            name = self.from_place(rel)
            if rel.endswith(".py"):
                found = test_ids(now, name)
                if found is None:
                    out.append(name)
                    continue
                if not found and TEST_MODULE.search(PurePosixPath(rel).name):
                    out.append(name)
                    continue
                was = self.before(rel)
                had = test_ids(was, name) if was is not None else {}
                out.extend(i for i, code in found.items()
                           if (had or {}).get(i) != code)
            elif WHOLE_FILE.search(PurePosixPath(rel).name):
                out.append(name)
        return out

    def lay_out(self, tree, changes):
        """write the place's start state and the run's test changes into a
        checkout of the start commit at `tree`, and nothing else."""
        tree = Path(tree)
        for rel, data in self.loose.items():
            target = tree / rel
            if data is None:
                if target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for rel, now in changes:
            target = tree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(now)

    def place_in(self, tree):
        """the place, inside a checkout of the same repo at `tree`."""
        return Path(tree) / self.place.relative_to(self.root)


def changed(before, now):
    """-> the paths in either {path: sha256} that are not the same in both."""
    return sorted(rel for rel in set(before) | set(now)
                  if before.get(rel) != now.get(rel))


def take(place, own=None):
    """-> a Snapshot of `place` now. it never raises: a place it cannot read
    gives one whose `why` says so."""
    return Snapshot(place, own=own)


def load(folder):
    """-> the Snapshot a run saved in `folder`, or None when it saved none
    or the file does not read as one."""
    try:
        data = json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
        shot = Snapshot(data["place"], why="loading")
        shot.root = Path(data["root"]) if data.get("root") else None
        shot.start = data.get("start")
        shot.own = data.get("own")
        shot.why = data.get("why") or ""
        shot.hashed = bool(data.get("hashed"))
        shot.ingit = bool(data.get("ingit"))
        shot.tests = dict(data.get("tests") or {})
        shot.specs = dict(data.get("specs") or {})
        shot.product = dict(data.get("product") or {})
        shot.loose = dict((rel, None if text is None
                           else base64.b64decode(text))
                          for rel, text in (data.get("loose") or {}).items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return shot
