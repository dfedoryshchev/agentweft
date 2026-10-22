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
import fnmatch
import hashlib
import os
import re
from pathlib import Path

FOLDER = "facts"
FOLDER_FILE = "_folder.md"
PROJECT_FILE = "_project.md"
# the files under facts/ that hold no entries of their own: the list the
# runner renders, and what the retro proposes for a person to do
INDEX = "INDEX.md"
PROPOSED = "PROPOSED.md"
NOT_FACTS = (INDEX, PROPOSED)
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

    def drop(self, key):
        self.fields = [(k, v) for k, v in self.fields if k != key]

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


HONOURED = re.compile(r"\bhonoured (\d+)")


def handed(root, paths, found=None):
    """-> the facts that hold for any of `paths`, each once: live before
    stale, `important` before the rest, the most honoured first, and
    otherwise nearest first, path by path in the order given."""
    found = read(root) if found is None else found
    seen, order = set(), []
    for path in paths:
        for fact in lookup(root, path, found=found):
            if fact.id not in seen:
                seen.add(fact.id)
                order.append(fact)

    def honoured(f):
        m = HONOURED.search(f.get("seen"))
        return int(m.group(1)) if m else 0

    return sorted(order, key=lambda f: (f.status != LIVE,
                                        f.label != "important", -honoured(f)))


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


CHECKED_FLAGS = set("nrREFiwqsHhl")
EXITS = re.compile(r"^(.*?)\s+exits?\s+(\S+)\s*$")
# what a check never reads: git's own files, caches that change whenever the
# tests run, and installed packages, too big to hash again after every step
NOT_READ = (".git", "__pycache__", ".pytest_cache", "node_modules", ".venv",
            "venv")
HELD, BROKEN, UNRUN = "held", "broken", "could not run"


class Check(object):
    """a fact's `check:` as the runner reads it: a grep, its patterns, its
    paths and the exit code that means the fact holds."""

    __slots__ = ("flags", "patterns", "paths", "include", "want")

    def __init__(self):
        self.flags = set()
        self.patterns = []
        self.paths = []
        self.include = []
        self.want = 0


def parse_check(text):
    """-> (Check, "") or (None, why it cannot run). a check is
    `grep [flags] <pattern> <path>... [exits <n>]`, the one shape the runner
    runs, in its own process."""
    import shlex

    text = (text or "").strip()
    want = 0
    m = EXITS.match(text)
    if m:
        if not re.match(r"^\d+$", m.group(2)):
            return None, "exits " + m.group(2) + " is not an exit code"
        text, want = m.group(1), int(m.group(2))
    try:
        words = shlex.split(text)
    except ValueError as e:
        return None, "it does not read as a command: " + str(e)
    if not words or words[0] != "grep":
        return None, ("only a grep runs as a fact's check, never "
                      + (words[0] if words else "nothing"))
    out = Check()
    out.want = want
    rest = words[1:]
    i = 0
    while i < len(rest):
        w = rest[i]
        if w == "--":
            i = i + 1
            break
        if w.startswith("--include="):
            out.include.append(w.split("=", 1)[1])
        elif w.startswith("--"):
            return None, "grep " + w + " is not one a check takes"
        elif w == "-e" and i + 1 < len(rest):
            out.patterns.append(rest[i + 1])
            i = i + 1
        elif w.startswith("-") and len(w) > 1:
            bad = [c for c in w[1:] if c not in CHECKED_FLAGS]
            if bad:
                return None, "grep -" + bad[0] + " is not one a check takes"
            out.flags.update(w[1:])
        else:
            break
        i = i + 1
    rest = rest[i:]
    if not out.patterns:
        if not rest:
            return None, "it names no pattern"
        out.patterns.append(rest[0])
        rest = rest[1:]
    out.include.extend(w.split("=", 1)[1] for w in rest
                       if w.startswith("--include="))
    rest = [w for w in rest if not w.startswith("--include=")]
    if not rest:
        return None, "it names no file to read"
    for p in rest:
        if p.startswith("-") or re.search(r"[;&|<>$`]", p):
            return None, p + " is not a path"
    out.paths = [norm(p) for p in rest]
    return out, ""


def bre(pattern):
    """-> a basic grep pattern as python reads it: `(`, `)`, `{`, `}`, `|`,
    `+` and `?` are plain unless a backslash makes them special."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            n = pattern[i + 1]
            out.append(n if n in "(){}|+?" else c + n)
            i = i + 2
            continue
        out.append("\\" + c if c in "(){}|+?" else c)
        i = i + 1
    return "".join(out)


def outside(root, rel):
    """whether `rel`, as a check names it, is not a path inside the place."""
    if not rel or rel.startswith("/") or os.path.isabs(rel) \
            or re.match(r"^[A-Za-z]:", rel):
        return True
    base = Path(os.path.abspath(str(root)))
    try:
        Path(os.path.abspath(str(base / rel))).relative_to(base)
    except ValueError:
        return True
    return False


def walk(root, base, own=None):
    """-> every file under `base`, in a fixed order, past the folders a check
    never reads: git's, caches, the runner's own and the store, which quotes
    the very lines its checks look for."""
    skip = set([Path(os.path.abspath(str(folder(root))))])
    if own is not None:
        skip.add(Path(os.path.abspath(str(own))))
    out = []
    for dirpath, dirs, names in os.walk(str(base)):
        here = Path(os.path.abspath(dirpath))
        dirs[:] = sorted(d for d in dirs if d not in NOT_READ
                         and here / d not in skip)
        out.extend(here / n for n in sorted(names))
    return out


def rel_of(root, path):
    return Path(os.path.abspath(str(path))).relative_to(
        Path(os.path.abspath(str(root)))).as_posix()


def run_check(root, text, own=None):
    """-> (True, "") when the check holds on the place now, (False, what
    grep found against what the fact says) when it does not, (None, "could
    not run: <why>") when it cannot say. it is read and run here, never
    handed to a shell or a process. `own` is the runner's folder."""
    check, why = parse_check(text)
    if check is None:
        return None, "could not run: " + why
    root = Path(root)
    flags = re.I if "i" in check.flags else 0
    try:
        found = []
        for p in check.patterns:
            if "F" in check.flags:
                p = re.escape(p)
            elif "E" not in check.flags:
                p = bre(p)
            if "w" in check.flags:
                p = r"(?<!\w)(?:" + p + r")(?!\w)"
            found.append(re.compile(p, flags))
    except re.error as e:
        return None, "could not run: the pattern does not read: " + str(e)
    files = []
    for rel in check.paths:
        if outside(root, rel):
            return None, "could not run: " + rel + " is not in the place"
        target = root / rel
        if target.is_dir():
            if not check.flags & set("rR"):
                return None, "could not run: " + rel + " is a folder"
            files.extend(walk(root, target, own))
        elif target.is_file():
            files.append(target)
        else:
            return None, "could not run: " + rel + " is not a file"
    first = None
    for path in files:
        if check.include and not any(fnmatch.fnmatch(path.name, g)
                                     for g in check.include):
            continue
        try:
            lines = text_lines(path)
        except OSError as e:
            return None, "could not run: " + rel_of(root, path) + ": " + str(e)
        for n, line in enumerate(lines, 1):
            if any(f.search(line) for f in found):
                first = (path, n, line)
                break
        if first:
            break
    code = 0 if first else 1
    if code == check.want:
        return True, ""
    said = "grep exits " + str(code) + ", the fact says " + str(check.want)
    if first:
        said = (said + ": " + rel_of(root, first[0]) + ":" + str(first[1])
                + ":" + first[2])
    return False, said


def check_paths(text):
    """-> the paths a check reads, [] when it does not parse."""
    check, _ = parse_check(text)
    return check.paths if check is not None else []


def scope_digest(root, scopes, own=None):
    """-> one sha256 of every file the scopes hold now, by content."""
    root = Path(root)
    parts = []
    for scope in scopes:
        scope = norm(scope)
        if scope == PROJECT or is_glob(scope):
            found = walk(root, root, own)
        elif scope.endswith("/"):
            found = walk(root, root / scope, own) \
                if (root / scope).is_dir() else []
        else:
            found = [root / scope]
        for path in found:
            rel = rel_of(root, path)
            if is_glob(scope) and rank(scope, rel) is None:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                data = None
            parts.append(rel + " " + (hashlib.sha256(data).hexdigest()
                                      if data is not None else "gone"))
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def index_lines(found):
    """-> facts/INDEX.md: one line per live fact, by scope, then the stale
    ones with why."""
    def one(f):
        return ("- " + f.id + " " + ", ".join(f.scopes)
                + (" " + f.label if f.label and f.label != "none" else "")
                + ": " + f.claim)

    live = sorted((f for f in found if f.status == LIVE),
                  key=lambda f: (f.scopes, f.id))
    stale = sorted((f for f in found if f.status == STALE),
                   key=lambda f: (f.scopes, f.id))
    out = ["# facts", "", "the runner writes this list; the entries are in the"
           " files beside it.", "", "## live", ""]
    out.extend([one(f) for f in live] or ["- none"])
    if stale:
        out.extend(["", "## stale", ""])
        out.extend(one(f) + " (stale: " + f.get("stale") + ")" for f in stale)
    return out


def write(path, head, found):
    """the one writer of a facts file: the runner's, never a step's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(head, found))
