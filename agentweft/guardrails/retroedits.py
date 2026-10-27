"""the doc, rules and test files the retro asks the runner to change, each
held to the tree as the run left it before anything is written.

an `edit:` names a file, the words in it `now:` and the words `after:`. the
runner writes it into the working tree, unstaged, only when:

- the file is a doc in the place: markdown, text, reStructuredText or
  asciidoc, or a README. not a spec (the person's word), not a test (a test
  comes in as a guard), not a file that holds a credential, and not under
  facts/ or the runner's own folder;
- the `now:` words are in it as written, once;
- every name the `after:` words quote, a `code span` or a `--flag`, is in a
  file of the tree as left that is not a doc, or is a command a gate of this
  run ran; an `evidence:`, when one is given, holds as a fact's does;
- no field looks like a secret (`factsguard.secret_in`);
- the run has not made `edits_per_run` of them and of guards already.

`CLAUDE.md`, `AGENTS.md`, `.claude/` and `rules/` may be edited, and are
named first wherever the changes are listed. a step that writes one is still
refused before the next step starts (`briefing.py`); the runner writes these
after the last step.

a `guard:` of kind test with `code:` lines is written as a new python test
file only when it passes on the tree as left: it runs with the flow's own
pytest, the way the start tests run, and one that fails, runs no test or
cannot run is taken out again. a gate or flow-key guard is a line for a
person.

the retro is handed the docs that name a file the run changed or a name its
diff added or removed (`named`), at most `DOCS` of them and `CHARS`
characters, so that each is confirmed current or edited.
"""
import re
from pathlib import Path, PurePosixPath

from agentweft.guardrails import briefing, factsguard, starttests
from agentweft.guardrails.snapshot import TEST_MODULE, is_spec, is_test
from agentweft.orchestrate import facts

# files a run's retro may have the runner change beyond facts/: doc edits
# and guards together
CAP = 3
SUFFIXES = (".md", ".markdown", ".rst", ".txt", ".adoc")
SPAN = re.compile(r"`([^`\n]+)`")
FLAG = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")
NAMED = re.compile(r"\b(?:def|class|function|interface|type)\s+([A-Za-z_]\w*)"
                   r"|\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*=")
# the docs and characters of them the retro is handed
DOCS = 6
CHARS = 4000
LINE = 200
# a file larger than this is not read for a name
BIG = 512 * 1024
TIMEOUT = 120
DOC, INSTRUCTION, GUARD = "doc", "instruction", "guard"


def cap_of(fm):
    """-> the flow's `edits_per_run`, CAP when it names none."""
    said = fm.get("edits_per_run") if hasattr(fm, "get") else None
    return CAP if said is None else int(said)


def is_doc(rel):
    name = PurePosixPath(rel).name.lower()
    return name.startswith("readme") or PurePosixPath(name).suffix in SUFFIXES


def is_instruction(rel):
    """whether `rel` is a file a model reads as its instructions."""
    return briefing.watched(rel) or rel.split("/")[0] == "rules"


def quoted(text):
    """-> each name `text` quotes: its code spans and its --flags, in order,
    each once."""
    out = []
    for name in SPAN.findall(text or "") + FLAG.findall(
            SPAN.sub(" ", text or "")):
        name = name.strip()
        if name and name not in out:
            out.append(name)
    return out


def unquoted(text):
    """-> `text` without one pair of quotes around all of it."""
    text = (text or "").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'`":
        return text[1:-1]
    return text


class Tree(object):
    """the text files of the place as the run left it that are not docs,
    read once: what a check never reads (`facts.walk`) left out. a doc is
    no witness for another, since it can be as stale as the one edited."""

    def __init__(self, root, own=None):
        self.root = Path(root)
        self.own = own
        self.read = None

    def texts(self):
        if self.read is None:
            self.read = []
            for path in facts.walk(self.root, self.root, self.own):
                if is_doc(path.name):
                    continue
                try:
                    if path.stat().st_size > BIG:
                        continue
                    data = path.read_bytes()
                except OSError:
                    continue
                if b"\0" in data:
                    continue
                self.read.append((facts.rel_of(self.root, path),
                                  data.decode("utf-8", "replace")))
        return self.read

    def holds(self, name, but=()):
        """whether `name` is in a file of the tree other than `but`."""
        return any(name in text for rel, text in self.texts()
                   if rel not in but)

    def changed(self, rel):
        self.read = None


def place_refusal(root, rel, own):
    """-> why the runner may not write `rel`, a path from the place, "" when
    it may."""
    if not rel:
        return "it names no file"
    what = factsguard.secret_in(rel)
    if what:
        return "it looks like a secret: " + what + " in the file"
    if facts.escapes(root, rel) or rel == facts.PROJECT:
        return rel + " is outside the place"
    parts = rel.split("/")
    if ".git" in parts:
        return rel + " is git's own"
    if parts[0] == facts.FOLDER:
        return rel + " is under facts/, which the runner writes as facts"
    if own is not None:
        try:
            (Path(root) / rel).resolve().relative_to(Path(own).resolve())
            return rel + " is in the runner's own folder"
        except ValueError:
            pass
    return ""


def edit_refusal(root, rel, fields, record, tree, own=None):
    """-> (why the edit is not made, "" when it is, the file's text after
    it). `fields` is the item's: now, after, because, evidence."""
    rel = facts.norm(rel)
    why = place_refusal(root, rel, own)
    if why:
        return why, None
    if is_spec(rel):
        return (rel + " is a spec file, the person's word: a change to it is"
                " theirs to make"), None
    if is_test(rel):
        return rel + " is a test file: a test comes in as a guard", None
    if not is_doc(rel):
        return (rel + " is not a doc (markdown, text, reStructuredText,"
                " asciidoc or a README)"), None
    for key in ("now", "after", "because", "evidence"):
        what = factsguard.secret_in(fields.get(key) or "")
        if what:
            return "it looks like a secret: " + what + " in " + key, None
    now, after = fields.get("now") or "", fields.get("after") or ""
    if not now.strip():
        return "it has no now", None
    if not after.strip():
        return "it has no after", None
    if not (fields.get("because") or "").strip():
        return "it has no because", None
    path = Path(root) / rel
    if not path.is_file():
        return rel + " is not a file in the place", None
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return rel + " is not utf-8 text", None
    found = now if now in text else unquoted(now)
    count = text.count(found) if found else 0
    if not count:
        return '"' + now + '" is not in ' + rel, None
    if count > 1:
        return ('"' + found + '" is in ' + rel + " " + str(count)
                + " times, so which one is not said"), None
    if found != now:
        after = unquoted(after)
    if after == found:
        return "after is what is there now", None
    ran = set(c for c, _ in getattr(record, "ran", ()) or ())
    for name in quoted(after):
        if factsguard.squash(name) in ran or tree.holds(name, but=(rel,)):
            continue
        return ("the after quotes " + name + ", which is not in the code as"
                " left (a doc does not count) or a command of this run"), None
    said = (fields.get("evidence") or "").strip()
    if said:
        held = record.holds("evidence: " + said)
        if held:
            return "the evidence does not hold: " + held, None
    return "", text.replace(found, after, 1)


def guard_refusal(root, rel, fields, own=None):
    """-> why a test guard is not written, before it runs, "" when it may
    be."""
    rel = facts.norm(rel)
    why = place_refusal(root, rel, own)
    if why:
        return why
    for key in ("what", "where"):
        what = factsguard.secret_in(fields.get(key) or "")
        if what:
            return "it looks like a secret: " + what + " in " + key
    what = factsguard.secret_in("\n".join(fields.get("code") or []))
    if what:
        return "it looks like a secret: " + what + " in code"
    if not is_test(rel) or not rel.endswith(".py") \
            or not TEST_MODULE.search(PurePosixPath(rel).name):
        return (rel + " is not a python test module (test_*.py or *_test.py"
                " under the tests), the one kind the runner can run")
    if (Path(root) / rel).exists():
        return rel + " is there already: a guard is a test file of its own"
    if not any(line.strip() for line in fields.get("code") or []):
        return "it has no code"
    return ""


def write_guard(root, rel, code, base, timeout=TIMEOUT):
    """-> "" once the test file `rel` is written and passes on the tree as
    left, else why not, with nothing left behind."""
    root = Path(root)
    path = root / rel
    made = [p for p in reversed(path.parents) if not p.exists()
            and root in p.parents]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(code).rstrip("\n") + "\n").encode("utf-8"))
    found, why = starttests.run_tests(base, [rel], root, timeout)
    if found is None:
        why = "it could not run: " + why
    elif not found:
        why = "no test in it ran"
    else:
        red = [(t, s) for t, s in sorted(found.items())
               if s[0] != "PASSED"]
        if red:
            t, (state, said) = red[0]
            why = ("it does not pass on the tree as left: " + t + " "
                   + state + (" - " + said if said else ""))
    if why:
        try:
            path.unlink()
        except OSError:
            pass
        for p in reversed(made):
            try:
                p.rmdir()
            except OSError:
                pass
    return why


class Keeper(object):
    """the edits and guards of one retro: the place, the runner's folder,
    the cap they share and how the flow starts pytest."""

    def __init__(self, root, own=None, cap=CAP, tests=None, timeout=TIMEOUT):
        self.root = Path(root)
        self.own = own
        self.cap = cap
        self.base = starttests.base_of(tests)
        self.timeout = timeout
        self.made = 0
        self.tree = Tree(self.root, own)

    def full(self):
        if self.made >= self.cap:
            return ("per-run cap: " + str(self.cap) + " doc edits and guards"
                    " are already made this run")
        return ""

    def edit(self, rel, fields, record):
        """-> why the edit is refused, "" once it is in the file."""
        why = self.full()
        if why:
            return why
        why, text = edit_refusal(self.root, rel, fields, record, self.tree,
                                 self.own)
        if why:
            return why
        (self.root / facts.norm(rel)).write_bytes(text.encode("utf-8"))
        self.tree.changed(rel)
        self.made = self.made + 1
        return ""

    def guard(self, rel, fields):
        """-> why the test guard is refused, "" once it is written and
        passes."""
        why = self.full() or guard_refusal(self.root, rel, fields, self.own)
        if why:
            return why
        why = write_guard(self.root, facts.norm(rel), fields.get("code") or [],
                          self.base, self.timeout)
        if why:
            return why
        self.tree.changed(rel)
        self.made = self.made + 1
        return ""


def names_of(diff):
    """-> (the names the diff took out, the names it put in): flags, and
    functions, classes and bindings, each on a removed or an added line and
    on no line of the other side."""
    gone, put = set(), set()
    for line in (diff or "").split("\n"):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("-"):
            gone.update(names_in(line[1:]))
        elif line.startswith("+"):
            put.update(names_in(line[1:]))
    return sorted(gone - put), sorted(put - gone)


def names_in(text):
    out = set(FLAG.findall(text))
    for m in NAMED.finditer(text):
        out.add(m.group(1) or m.group(2))
    return set(n for n in out if len(n) >= 4)


def docs_in(root, own=None):
    """-> the docs of the place a retro may edit, instruction files first,
    then by path."""
    found = []
    for path in facts.walk(root, root, own):
        rel = facts.rel_of(root, path)
        if is_doc(rel) and not is_spec(rel) and not is_test(rel) \
                and not place_refusal(root, rel, own):
            found.append(rel)
    return sorted(found, key=lambda r: (not is_instruction(r), r))


def named(root, changed, names=(), own=None, docs=DOCS, chars=CHARS):
    """-> a line per doc of the place that names a file in `changed` or one
    of `names`, with the lines that name them, at most `docs` docs and
    `chars` characters; the docs left out at the cap are named."""
    root = Path(root)
    terms = []
    for rel in changed or []:
        for term in (rel, PurePosixPath(rel).name):
            if term not in terms and (term == rel or "." in term):
                terms.append(term)
    words = [n for n in names or () if n not in terms]
    if not terms and not words:
        return []
    pattern = re.compile("|".join(
        [re.escape(t) for t in terms]
        + [r"(?<![\w-])" + re.escape(w) + r"(?![\w-])" for w in words]))
    out, left, used, kept = [], [], 0, 0
    for rel in docs_in(root, own):
        try:
            lines = facts.text_lines(root / rel)
        except OSError:
            continue
        hits = [(n, l) for n, l in enumerate(lines, 1) if pattern.search(l)]
        if not hits:
            continue
        said = sorted(set(m.group(0) for _, l in hits
                          for m in pattern.finditer(l)))
        block = ["- " + rel + (" (instruction file)" if is_instruction(rel)
                               else "") + " names " + ", ".join(said) + ":"]
        block.extend("  " + rel + ":" + str(n) + ": " + l.strip()[:LINE]
                     for n, l in hits)
        size = sum(len(b) + 1 for b in block)
        if kept >= docs or used + size > chars:
            left.append(rel)
            continue
        out.extend(block)
        used, kept = used + size, kept + 1
    if left:
        out.append("- left out at the cap of " + str(docs) + " docs and "
                   + str(chars) + " characters: " + ", ".join(left))
    return out
