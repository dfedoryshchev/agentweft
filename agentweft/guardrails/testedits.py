"""the tests a run started with, held as the run found them.

a step that cannot make the product pass a test can make the test pass the
product: loosen its assertion, drop it, or delete its file. so after every
step each test file the start snapshot hashed is read against how the run
found it:

- a python test file is compared per test function, by its syntax tree: a
  test the run started with that is gone or whose code is not what it was is
  a change, and so is a change to the code its tests share (a constant, a
  fixture, a helper), including a name the file had that is bound again
  further down to something else, and code added that changes how those
  tests run (a `pytestmark`, an autouse fixture, a module patched as the
  file loads, a new name a start test reads or takes as a fixture).
  formatting and comments are not; new names are not, on an import line of
  their own or added to one the file had, and neither is a new test in a
  test class the file had, so a test added beside the others can import
  what it needs.
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
import textwrap
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
CLAIMED_ON = "claimed on"


class Edit(object):
    """one test file the run started with that is not as it was. `items` is
    [(test id, or the file when the change is the file's, how it changed)];
    `added` how many tests or lines it gained; `unread` that what it held at
    the start cannot be read back; `shared_by` the tests of a python file
    that run against a change to the code they share (`sharing`); `was` and
    `now` the file's text as the run found it and as it is (None when gone
    or not read)."""

    __slots__ = ("path", "items", "added", "unread", "shared_by", "was",
                 "now")

    def __init__(self, path, items=(), added=0, unread=False, shared_by=()):
        self.path = path
        self.items = list(items)
        self.added = added
        self.unread = unread
        self.shared_by = list(shared_by)
        self.was = None
        self.now = None


def _text(data):
    return data.decode("utf-8", "replace")


def _is_test_func(node):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
        node.name.startswith("test")


def _docstring(node):
    return isinstance(node, ast.Expr) and \
        isinstance(node.value, ast.Constant) and \
        isinstance(node.value.value, str)


def _pieces(tree):
    """-> [(key, node, the collected test class it is in or None)] for the
    code at the top of `tree` that is neither a test, an import nor a
    docstring, the members of a collected test class one by one."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or \
                _is_test_func(node) or _docstring(node):
            continue
        if isinstance(node, ast.ClassDef) and collected(node):
            for member in node.body:
                if not _is_test_func(member) and not _docstring(member):
                    out.append((node.name + "." + ast.dump(member), member,
                                node.name))
            continue
        out.append((ast.dump(node), node, None))
    return out


def shared(source):
    """-> a Counter of the code in `source` that is neither a test, an
    import nor a docstring, each piece as a dump of its syntax tree."""
    return Counter(key for key, _, _ in _pieces(ast.parse(source)))


def _autouse(decorator):
    return isinstance(decorator, ast.Call) and any(
        k.arg in ("autouse", None) and not (
            isinstance(k.value, ast.Constant) and not k.value.value)
        for k in decorator.keywords)


def _plain(target):
    if isinstance(target, (ast.Tuple, ast.List)):
        return all(_plain(t) for t in target.elts)
    return isinstance(target, ast.Name) and not target.id.startswith("pytest")


def _acts(node):
    """whether a statement added beside the tests changes how the tests
    around it run: anything but a definition or an assignment to plain
    names, a name pytest reads (`pytestmark`, `pytest_plugins`) and a
    fixture with autouse among them."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name.startswith("pytest") or \
            any(_autouse(d) for d in node.decorator_list)
    if isinstance(node, ast.Assign):
        return not all(_plain(t) for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return not _plain(node.target)
    return True


def _start_tests(tree):
    for node in tree.body:
        if _is_test_func(node):
            yield node
        elif isinstance(node, ast.ClassDef) and collected(node):
            for member in node.body:
                if _is_test_func(member):
                    yield member


def added_code(was, now):
    """whether code `now` gained beside the tests `was` held changes how
    those tests run: a new piece `_acts` holds, at the top or in a test
    class the file had, or a new name a start test reads or takes as a
    fixture, which it found elsewhere before."""
    then, later = ast.parse(was), ast.parse(now)
    classes = {n.name for n in then.body
               if isinstance(n, ast.ClassDef) and collected(n)}
    before = shared(was)
    for key, node, owner in _pieces(later):
        if owner is not None and owner not in classes:
            continue
        if before[key] > 0:
            before[key] -= 1
        elif _acts(node):
            return True
    used = set()
    for test in _start_tests(then):
        for n in ast.walk(test):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                used.add(n.id)
            elif isinstance(n, ast.arg):
                used.add(n.arg)
    bound = last_bindings(was)
    return any(name in used and name not in bound
               for name in last_bindings(now))


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


def _reads(node):
    """-> the names `node` reads or takes as a fixture."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
    return out


def _graph(*trees):
    """-> {name bound at the top of any of `trees`: the names its code
    reads}, so a helper reaches what it calls."""
    out = {}
    for tree in trees:
        for node in tree.body:
            for bound, _ in _bound(node):
                out.setdefault(bound, set()).update(_reads(node))
    return out


def sharing(name, was, now):
    """-> the ids of the tests `was` held that run against what changed in
    the code they share in `now`: each that reads, itself or through the
    helpers it calls, a name bound to something else now or one `now` binds
    that `was` did not. every one when the change is not such a name (a
    fixture with autouse, a name pytest reads, a call as the file loads, a
    member of a test class) or no test can be shown to read it."""
    old = test_ids(was, name) or {}
    every = list(old)
    then, later = last_bindings(was), last_bindings(now)
    names = {n for n, code in then.items() if later.get(n) != code}
    names |= {n for n in later if n not in then}
    first, last = ast.parse(was), ast.parse(now)
    autouse = {n.name for t in (first, last) for n in t.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and any(_autouse(d) for d in n.decorator_list)}
    loose = (Counter(k for k, n, _ in _pieces(first) if not _bound(n))
             != Counter(k for k, n, _ in _pieces(last) if not _bound(n)))
    if loose or not names or any("." in n or n.startswith("pytest")
                                 or n in autouse for n in names):
        return every
    graph = _graph(first, last)
    out = []
    for test, node in _named_tests(first, name):
        seen, todo = set(), list(_reads(node))
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo.extend(graph.get(n, ()))
        if seen & names:
            out.append(test)
    return out or every


def _named_tests(tree, name):
    for node in tree.body:
        if _is_test_func(node):
            yield name + "::" + node.name, node
        elif isinstance(node, ast.ClassDef) and collected(node):
            for member in node.body:
                if _is_test_func(member):
                    yield name + "::" + node.name + "::" + member.name, member


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
    by = []
    if shared(was) - shared(now) or rebound(was, now) or \
            (old and added_code(was, now)):
        items.append((name, SHARED))
        by = sharing(name, was, now)
    return Edit(name, items, len(set(new) - set(old)), shared_by=by)


def added_only(name, was, now):
    """whether python test source `now` holds every test of `was` and the
    code they share as they were, read as the check reads a test file: what
    it gained is tests, names on an import line, formatting or comments.
    False when either does not parse or the file is gone (`now` None)."""
    found = _python(name, was, now)
    return found is not None and not found.items


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
        found = (_python(name, was, data) if python else None) \
            or _lines(name, was, data)
        found.was, found.now = was, data
        out.append(found)
    return out


def _source_of(source, name, test):
    """-> the code of the test `test` (an id under `name`) in `source`, or
    ""."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for t, node in _named_tests(tree, name):
        if t == test:
            return ast.get_source_segment(source, node) or ""
    return ""


def read_by(source, name, test):
    """-> the code of the test `test` (an id under `name`) in `source`, and
    of each statement at the top of the file that binds a name it reads or
    takes as a fixture, itself or through what those read (a constant, a
    helper, a fixture), each dedented; "" when the test is not there or the
    source does not parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    node = next((n for t, n in _named_tests(tree, name) if t == test), None)
    if node is None:
        return ""
    graph = _graph(tree)
    seen, todo = set(), list(_reads(node))
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(graph.get(n, ()))
    parts = [node] + [top for top in tree.body if top is not node and any(
        bound in seen for bound, _ in _bound(top))]
    return "\n\n".join(textwrap.dedent(
        ast.get_source_segment(source, part, padded=True) or "")
        for part in parts)


def claimable(test, how):
    """whether a change a WRONG TEST line under a ruling may cover: a test
    whose code changed, or a file whose lines or shared code did. a test
    removed, a file deleted or one that no longer parses is not."""
    if "::" in test:
        return how == CHANGED
    return how == SHARED or how.endswith(" removed or rewritten")


def claimed_by(edit, test, how):
    """-> what a WRONG TEST line has to name for the change `test`, `how`, in
    `edit` to stand: the test itself; for the code a python file's tests
    share, every test the file started with that runs against the change
    (`sharing`); for a file read by line, the file. [] for a change no claim
    covers."""
    if not claimable(test, how):
        return []
    if "::" not in test and how == SHARED:
        return list(edit.shared_by)
    return [test]


def what(n, edit):
    word = "line" if not edit.path.endswith(".py") else "test"
    return str(n) + " " + word + ("" if n == 1 else "s")


def passed(found, ruled):
    """-> the passing line for test files that only gained tests, or whose
    changes a ruling covers. `ruled` is [(test id or file, the ruling's
    stamp, the cite of the WRONG TEST claim it rests on or "")]."""
    said = [e.path + ": " + what(e.added, e) + " added"
            for e in found if not e.unread]
    line = "; ".join(said)
    if ruled:
        line += (". " if line else "") + "changed, each covered by a" \
            " ruling: " + ", ".join(
                t + " (ruling " + by + ")"
                + (" " + CLAIMED_ON + " " + cite if cite else "")
                for t, by, cite in ruled)
    elif said:
        line += ", none the run started with changed"
    unread = [e.path for e in found if e.unread]
    if unread:
        line += ("; " if line else "") + "not compared, the run has no start" \
            " commit to read them from: " + ", ".join(unread)
    return Result(NAME, True, line)


def held(step, left, overridden=False):
    """-> the failed gate for a step that changed tests the run started
    with. `left` is [(test id or file, how it changed)]; `overridden` that
    the run holds an override, under which a WRONG TEST line may cover
    one."""
    return Result(NAME, False, step + " changed tests the run started with: "
                  + ", ".join(t + " (" + how + ")" for t, how in left)
                  + ". put each back as the run found it; a new test goes in"
                  " as a test of its own. a ruling in decisions.md that names"
                  " the test, or quotes the spec line that decides it, lets"
                  " the change stand" + (
                      ", and so does a WRONG TEST line for the test whose"
                      " spec: line quotes a line the override lets change, as"
                      " the run found it or as the ruled edit left it"
                      if overridden else ""))
