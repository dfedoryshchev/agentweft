"""what is known about a file, a folder or the whole project, and why.

decisions.md holds rulings, one flat list that whoever reads it reads all of.
this is the other half: a fact is keyed to where it holds, so a step handed a
file can be handed what is known about that file and nothing else. a fact on
a folder holds for every file inside it, and one on the project for all of
them.

it lives beside decisions.md, under `<root>/facts/`, as plain markdown a
person reads in a diff:

    facts/<path>.md            the facts of one file (facts/pkg/a.py.md)
    facts/<folder>/_folder.md  the facts of a folder
    facts/_project.md          the facts of the whole project

where an entry sits is only where a person finds it: every entry under
`facts/` is read, and its `scope:` lines say where it holds. one entry:

    ## F-0007 live
    scope: pkg/parse.py
    kind: convention
    claim: every user-facing error is raised, never printed here
    why: the spec's one-line stderr rule; a print here broke it once
    anchor: pkg/parse.py:12-19 sha256:3f1c...

a scope is a file path, a folder path ending in `/`, a glob (`pkg/**`) or
`.` for the project; an entry may name several. the anchor is the lines the
fact is about and the sha256 of their text. at the start of every run
`heal` hashes them again: the same text where it was is nothing to do, the
same text in one other place in the file moves the anchor there, anything
else marks the fact `stale` with the day and why, and a fact whose file is
gone in two runs is `retired`. a fact with no anchor is never stale by
content.
"""
import datetime
import hashlib
import os
import re
from pathlib import Path

FOLDER = "facts"
FOLDER_FILE = "_folder.md"
PROJECT_FILE = "_project.md"
# the files under facts/ that hold no entries of their own
NOT_FACTS = ("INDEX.md", "PROPOSED.md")
PROJECT = "."

LIVE, STALE, SUPERSEDED, RETIRED = "live", "stale", "superseded", "retired"
STATUSES = (LIVE, STALE, SUPERSEDED, RETIRED)
KINDS = ("decision", "convention", "why", "defect", "gate-issue")
LABELS = ("important", "wip", "investigation")

HEADING = re.compile(r"^## (F-\d+) (" + "|".join(STATUSES) + r")\s*$")
FIELD = re.compile(r"^([a-z][a-z-]*):\s?(.*)$")
ANCHOR = re.compile(r"^(?P<path>.+):(?P<first>\d+)-(?P<last>\d+)"
                    r"(?:\s+sha256:(?P<sha>[0-9a-f]{64}))?\s*$")
GONE = "file gone"
# runs that find an anchored file gone before its fact is retired
GONE_RUNS = 2
GONE_COUNT = re.compile(r"file gone in (\d+) runs?")


class Fact(object):
    """one entry: its id, its status, its fields in the order written, and
    the file under facts/ it was read from."""

    __slots__ = ("id", "status", "fields", "file")

    def __init__(self, id, status, fields=None, file=None):
        self.id = id
        self.status = status
        self.fields = list(fields or [])
        self.file = file

    def get(self, key, default=""):
        for k, v in self.fields:
            if k == key:
                return v
        return default

    def all(self, key):
        return [v for k, v in self.fields if k == key]

    def put(self, key, value):
        """set the first `key` to value, or add it at the end."""
        for n, (k, _) in enumerate(self.fields):
            if k == key:
                self.fields[n] = (key, value)
                return
        self.fields.append((key, value))

    @property
    def scopes(self):
        return [norm(s) for s in self.all("scope") if s.strip()]

    @property
    def claim(self):
        return self.get("claim")

    @property
    def why(self):
        return self.get("why")

    @property
    def kind(self):
        return self.get("kind")

    @property
    def label(self):
        return self.get("label")

    def lines(self):
        return (["## " + self.id + " " + self.status]
                + [k + ": " + v for k, v in self.fields])


class Anchor(object):
    __slots__ = ("path", "first", "last", "sha")

    def __init__(self, path, first, last, sha=None):
        self.path = norm(path)
        self.first = first
        self.last = last
        self.sha = sha

    def __str__(self):
        out = self.path + ":" + str(self.first) + "-" + str(self.last)
        return out + (" sha256:" + self.sha if self.sha else "")


def anchor_of(fact):
    """-> the fact's Anchor, None when it has none or it does not read."""
    said = fact.get("anchor").strip()
    m = ANCHOR.match(said) if said else None
    if not m:
        return None
    first, last = int(m["first"]), int(m["last"])
    if first < 1 or last < first:
        return None
    return Anchor(m["path"].strip(), first, last, m["sha"])


def norm(path):
    """-> a path as a scope compares it: forward slashes, no leading `./`."""
    path = (path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if path in ("", "."):
        return PROJECT
    while "//" in path:
        path = path.replace("//", "/")
    return path


def relative(root, path):
    """-> `path` as a scope compares it, relative to `root` when it is an
    absolute path under it."""
    given = str(path)
    if os.path.isabs(given):
        try:
            given = Path(os.path.abspath(given)).relative_to(
                Path(os.path.abspath(str(root)))).as_posix()
        except ValueError:
            pass
    return norm(given)


def folder(root):
    return Path(root) / FOLDER


def file_for(scope):
    """-> where under facts/ an entry for `scope` is written."""
    scope = norm(scope)
    if scope == PROJECT or is_glob(scope):
        return PROJECT_FILE
    if scope.endswith("/"):
        return scope + FOLDER_FILE
    return scope + ".md"


def parse(text, file=None):
    """-> (the lines before the first entry, [Fact]) of one file's text."""
    head, out = [], []
    for raw in text.replace("\r\n", "\n").split("\n"):
        m = HEADING.match(raw)
        if m:
            out.append(Fact(m.group(1), m.group(2), file=file))
            continue
        if not out:
            head.append(raw)
            continue
        f = FIELD.match(raw)
        if f:
            out[-1].fields.append((f.group(1), f.group(2).strip()))
    while head and not head[-1].strip():
        head.pop()
    return head, out


def render(head, found):
    out = list(head)
    for fact in found:
        if out:
            out.append("")
        out.extend(fact.lines())
    return "\n".join(out) + "\n"


def files(root):
    """-> every file under facts/ that holds entries, in a fixed order."""
    base = folder(root)
    if not base.is_dir():
        return []
    return sorted((p for p in base.rglob("*.md")
                   if p.is_file() and not (p.parent == base
                                           and p.name in NOT_FACTS)),
                  key=lambda p: p.relative_to(base).as_posix())


def read(root):
    """-> every entry under facts/, of every status, file by file."""
    out = []
    for path in files(root):
        _, found = parse(path.read_text(encoding="utf-8", errors="replace"),
                         file=path)
        out.extend(found)
    return out


def is_glob(scope):
    return any(c in scope for c in "*?[")


def glob_re(pattern):
    """`**` crosses folders, `*` and `?` stay inside one."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i = i + 2
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?"
                   else re.escape(c))
        i = i + 1
    return re.compile("^" + "".join(out) + "$")


def same(a, b):
    if os.name == "nt":
        return a.casefold() == b.casefold()
    return a == b


def rank(scope, path):
    """-> how close `scope` holds for `path`: 0 the file itself, then each
    folder up from it, then a glob, then the project; None when it does
    not hold."""
    if scope == PROJECT:
        return 10 ** 6 + 1
    if is_glob(scope):
        hit = glob_re(scope.casefold() if os.name == "nt" else scope).match(
            path.casefold() if os.name == "nt" else path)
        return 10 ** 6 if hit else None
    if scope.endswith("/"):
        inside = path.casefold() if os.name == "nt" else path
        if not inside.startswith(scope.casefold() if os.name == "nt"
                                 else scope):
            return None
        return path.count("/") - scope.count("/") + 1
    return 0 if same(scope, path) else None


def lookup(root, path, found=None):
    """-> the facts that hold for `path`, live and stale, nearest first: the
    file's own, then each folder up from it, then the globs that match it,
    then the project's. `found` is every entry, when already read."""
    path = relative(root, path)
    picked = []
    for fact in read(root) if found is None else found:
        if fact.status not in (LIVE, STALE):
            continue
        ranks = [r for r in (rank(s, path) for s in fact.scopes)
                 if r is not None]
        if ranks:
            picked.append((min(ranks), fact))
    picked.sort(key=lambda p: p[0])
    return [f for _, f in picked]


def text_lines(path):
    return path.read_text(encoding="utf-8", errors="replace").replace(
        "\r\n", "\n").split("\n")


def digest(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def anchored(root, path, first, last):
    """-> the Anchor of lines first..last of `path` as they are now, None
    when the file does not hold them."""
    target = Path(root) / norm(path)
    if not target.is_file():
        return None
    lines = text_lines(target)
    if first < 1 or last > len(lines) or last < first:
        return None
    return Anchor(path, first, last, digest(lines[first - 1:last]))


class Change(object):
    """what `heal` did to one fact: `how` is moved, stale, retired or back."""

    __slots__ = ("id", "how", "said")

    def __init__(self, id, how, said):
        self.id = id
        self.how = how
        self.said = said

    def __str__(self):
        return self.id + " " + self.how + ": " + self.said


def heal_one(root, fact, today):
    """-> the Change `heal` makes to one fact, None for none."""
    at = anchor_of(fact)
    if fact.status not in (LIVE, STALE) or at is None or not at.sha:
        return None
    target = Path(root) / at.path
    if not target.is_file():
        was = GONE_COUNT.search(fact.get("stale"))
        runs = (int(was.group(1)) if was else 0) + 1
        if runs >= GONE_RUNS:
            fact.status = RETIRED
            fact.put("retired", today + " " + GONE + " in " + str(runs)
                     + " runs")
            return Change(fact.id, RETIRED, at.path + " is gone")
        fact.status = STALE
        fact.put("stale", today + " " + GONE + " in " + str(runs) + " run")
        return Change(fact.id, STALE, at.path + " is gone")
    lines = text_lines(target)
    n = at.last - at.first + 1
    if at.last <= len(lines) and digest(lines[at.first - 1:at.last]) == at.sha:
        if fact.status == STALE:
            fact.status = LIVE
            fact.put("healed", today + " back as anchored")
            return Change(fact.id, "back", str(at))
        return None
    hits = [i for i in range(len(lines) - n + 1)
            if digest(lines[i:i + n]) == at.sha]
    if len(hits) == 1:
        moved = Anchor(at.path, hits[0] + 1, hits[0] + n, at.sha)
        fact.put("anchor", str(moved))
        fact.put("healed", today + " moved " + str(at.first) + "-"
                 + str(at.last) + " to " + str(moved.first) + "-"
                 + str(moved.last))
        fact.status = LIVE
        return Change(fact.id, "moved", str(moved))
    if fact.status == STALE:
        return None
    fact.status = STALE
    why = "lines changed" if not hits else "the lines are in " \
        + str(len(hits)) + " places now"
    fact.put("stale", today + " " + why + " since it was anchored")
    return Change(fact.id, STALE, at.path + ":" + str(at.first) + "-"
                  + str(at.last) + " " + why)


def heal(root, today=None):
    """-> every Change made, once per run, before the run takes its start:
    each anchored live or stale fact is hashed again and its status and
    anchor rewritten in its file. nothing else in the file changes."""
    today = today or datetime.date.today().isoformat()
    out = []
    for path in files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        head, found = parse(text, file=path)
        made = [c for c in (heal_one(root, f, today) for f in found) if c]
        if made:
            write(path, head, found)
            out.extend(made)
    return out


def write(path, head, found):
    """the one writer of a facts file: the runner's, never a step's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(head, found))
