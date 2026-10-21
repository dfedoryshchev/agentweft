"""the tests a run started with, held as the run found them.

a step that cannot make the product pass a test can make the test pass the
product: loosen its assertion, drop it, or delete its file. so after every
step each test file the start snapshot hashed is read against how the run
found it:

- a python test file is compared per test function, by its syntax tree: a
  test the run started with that is gone or whose code is not what it was is
  a change, and so is a change to the code its tests share (a constant, a
  fixture, a helper), including a name the file had that is bound again
  further down to something else. formatting and comments are not; new
  names are not, on an import line of their own or added to one the file
  had, and neither is a new test in a test class the file had, so a test
  added beside the others can import what it needs.
- a test file in another language (`*.test.ts`, `*Tests.cs`, `*_test.go`) is
  compared by line: a line removed or rewritten is a change.
- a file deleted is a change to every test it held.

a test added to a file the run found is the run's own, and red-first proves
it. which files changed is read from content hashes and what they held from
the start commit (or the snapshot, for a file already loose), so a step that
commits its edit is read the same as one that leaves it in the work tree. a
place with no start commit has only the hashes: a test file it cannot read
back is held as changed, since nothing can show the change was an addition.
"""
import ast
from collections import Counter
from pathlib import PurePosixPath

from agentweft.guardrails import specfiles
from agentweft.guardrails.gates.base import Result
from agentweft.guardrails.snapshot import WHOLE_FILE, _read, collected, \
    test_ids

NAME = "test-edits"
CHANGED = "changed"
REMOVED = "removed"
DELETED = "deleted with its file"
SHARED = "the code its tests share changed"
UNPARSED = "no longer parses"
UNREAD = "changed, with no start commit to compare it against"


class Edit(object):
    """one test file the run started with that is not as it was. `items` is
    [(test id, or the file when the change is the file's, how it changed)];
    `added` how many tests or lines it gained; `unread` that what it held at
    the start cannot be read back."""

    __slots__ = ("path", "items", "added", "unread")

    def __init__(self, path, items=(), added=0, unread=False):
        self.path = path
        self.items = list(items)
        self.added = added
        self.unread = unread


def _text(data):
    return data.decode("utf-8", "replace")


def _is_test_func(node):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
        node.name.startswith("test")


def _docstring(node):
    return isinstance(node, ast.Expr) and \
        isinstance(node.value, ast.Constant) and \
        isinstance(node.value.value, str)


def shared(source):
    """-> a Counter of the code in `source` that is neither a test, an
    import nor a docstring, each piece as a dump of its syntax tree."""
    out = Counter()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or \
                _is_test_func(node) or _docstring(node):
            continue
        if isinstance(node, ast.ClassDef) and collected(node):
            for member in node.body:
                if not _is_test_func(member) and not _docstring(member):
                    out[node.name + "." + ast.dump(member)] += 1
            continue
        out[ast.dump(node)] += 1
    return out


COMPOUND = (ast.If, ast.Try, ast.With, ast.For, ast.While)


def _bound(node, top=True):
    """-> [(name, what it is bound to)] for the names a statement binds, at
    the level it runs at: each name of an import on its own, so a name added
    to an import line leaves the others as they were; a test function as
    "test", its code being compared test by test; a collected test class at
    the top as its bases and decorators, its members being read one by one;
    anything else as the whole statement."""
    if isinstance(node, ast.Import):
        return [(a.asname or a.name.split(".")[0],
                 "import " + (a.name if a.asname else a.name.split(".")[0]))
                for a in node.names]
    if isinstance(node, ast.ImportFrom):
        source = "from " + "." * node.level + (node.module or "") + " import "
        return [(a.asname or a.name, source + a.name) for a in node.names]
    if _is_test_func(node):
        return [(node.name, "test")]
    if top and isinstance(node, ast.ClassDef) and collected(node):
        return [(node.name, "class " + " ".join(
            ast.dump(n) for n in node.bases + node.keywords
            + node.decorator_list))]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(node.name, ast.dump(node))]
    if isinstance(node, (ast.Assign, ast.Delete)):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    else:
        targets = []
    return [(n.id, ast.dump(node)) for t in targets for n in ast.walk(t)
            if isinstance(n, ast.Name)]


def last_bindings(source):
    """-> {name: what it is bound to last, as `_bound` reads it} for every
    name bound at the top of `source` or in a collected test class, the
    bodies of an if, a try, a with or a loop there included: what a test
    that uses the name gets when it runs."""
    out = {}

    def walk(body, within=""):
        for node in body:
            for name, code in _bound(node, not within):
                out[within + name] = code
            if isinstance(node, ast.ClassDef) and not within \
                    and collected(node):
                walk(node.body, node.name + ".")
            elif isinstance(node, COMPOUND):
                for part in ("body", "orelse", "finalbody"):
                    walk(getattr(node, part, None) or [], within)
                for handler in getattr(node, "handlers", None) or []:
                    walk(handler.body, within)

    walk(ast.parse(source).body)
    return out


def rebound(was, now):
    """whether a name the file bound when the run started is bound last to
    something else now: a helper, fixture or test bound again below the
    tests that use it changes them though their own code is as it was."""
    then, later = last_bindings(was), last_bindings(now)
    return any(later.get(name) != code for name, code in then.items())


def _python(name, was, now):
    old = test_ids(was, name)
    if old is None:
        return None
    if now is None:
        return Edit(name, [(t, DELETED) for t in old] or [(name, DELETED)])
    new = test_ids(now, name)
    if new is None:
        return Edit(name, [(name, UNPARSED)])
    items = []
    for t, code in old.items():
        if t not in new:
            items.append((t, REMOVED))
        elif new[t] != code:
            items.append((t, CHANGED))
    if shared(was) - shared(now) or rebound(was, now):
        items.append((name, SHARED))
    return Edit(name, items, len(set(new) - set(old)))


def _lines(name, was, now):
    if now is None:
        return Edit(name, [(name, DELETED)])
    gone = specfiles.lost(was, now)
    items = [(name, specfiles.lines(len(gone)) + " removed or rewritten")] \
        if gone else []
    return Edit(name, items, specfiles.added(was, now))


def changes(start):
    """-> an Edit for each test file the run started with that is not as it
    was, in path order. files that are not test code (data under a test
    folder) and files the run added are not read."""
    if start is None or not start.hashed:
        return []
    now = start.hashes()[0]
    out = []
    for rel in sorted(start.tests):
        if now.get(rel) == start.tests[rel]:
            continue
        python = rel.endswith(".py")
        if not python and not WHOLE_FILE.search(PurePosixPath(rel).name):
            continue
        name = start.from_place(rel)
        was = start.before(rel)
        if was is None:
            out.append(Edit(name, [(name, UNREAD)], unread=True))
            continue
        data = _read(start.root / rel) if rel in now else None
        was, data = _text(was), None if data is None else _text(data)
        found = _python(name, was, data) if python else None
        out.append(found or _lines(name, was, data))
    return out


def what(n, edit):
    word = "line" if not edit.path.endswith(".py") else "test"
    return str(n) + " " + word + ("" if n == 1 else "s")


def passed(found, ruled):
    """-> the passing line for test files that only gained tests, or whose
    changes a ruling covers. `ruled` is [(test id or file, the ruling's
    stamp)]."""
    said = [e.path + ": " + what(e.added, e) + " added"
            for e in found if not e.unread]
    line = "; ".join(said)
    if ruled:
        line += (". " if line else "") + "changed, each covered by a" \
            " ruling: " + ", ".join(t + " (ruling " + by + ")"
                                    for t, by in ruled)
    elif said:
        line += ", none the run started with changed"
    unread = [e.path for e in found if e.unread]
    if unread:
        line += ("; " if line else "") + "not compared, the run has no start" \
            " commit to read them from: " + ", ".join(unread)
    return Result(NAME, True, line)


def held(step, left):
    """-> the failed gate for a step that changed tests the run started
    with. `left` is [(test id or file, how it changed)]."""
    return Result(NAME, False, step + " changed tests the run started with: "
                  + ", ".join(t + " (" + how + ")" for t, how in left)
                  + ". put each back as the run found it; a new test goes in"
                  " as a test of its own. a ruling in decisions.md that names"
                  " the test, or quotes the spec line that decides it, lets"
                  " the change stand")
