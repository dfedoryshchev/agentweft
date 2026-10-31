"""the project's docs that name what a run changed, handed to the retro and
to a step.

the retro is handed the docs that name a file the run changed or a name its
diff added or removed (`named`), at most `DOCS` of them and `CHARS`
characters, so that each is confirmed current or kept as a nice-to-do ticket
on that doc: neither the retro nor the runner changes a doc for it. a step is
handed the same lines for the files it is handed, at most `DOCS_HANDED` docs
and `CHARS_HANDED` characters, the nearest doc first.

a doc is markdown, text, reStructuredText or asciidoc, or a README, in the
place: not a dependency or build manifest (requirements.txt and the rest,
`preflight.manifest`), not a file inside a python package but its README (it
ships with the code), not a spec, not a test, not decisions.md (its rulings
reach a step as rulings already), and not under facts/ or the runner's own
folder. `CLAUDE.md`, `AGENTS.md`, `.claude/` and `rules/` are named first.
"""
import re
from pathlib import Path, PurePosixPath

from agentweft.guardrails import briefing, factsguard
from agentweft.guardrails.snapshot import is_runners, is_spec, is_test
from agentweft.mcp import preflight
from agentweft.orchestrate import facts

SUFFIXES = (".md", ".markdown", ".rst", ".txt", ".adoc")
FLAG = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")
NAMED = re.compile(r"\b(?:def|class|function|interface|type)\s+([A-Za-z_]\w*)"
                   r"|\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*=")
# the docs and characters of them the retro is handed
DOCS = 6
CHARS = 4000
# the docs and characters of them a step is handed for its files
DOCS_HANDED = 3
CHARS_HANDED = 1500
# the line naming the docs left out at the cap
LEFT_LINE = 300
ON_MACHINE = "(a line that names a path on the machine, not quoted)"
LINE = 200


def is_doc(rel):
    """whether `rel` is a doc by its name: a doc suffix or a README, never a
    dependency or build manifest such as requirements.txt."""
    name = PurePosixPath(rel).name.lower()
    if preflight.manifest(name):
        return False
    path = PurePosixPath(name)
    return path.suffix in SUFFIXES or path.stem == "readme" and (
        not path.suffix or path.suffix in SUFFIXES)


def packaged(root, rel):
    """-> the folder of `rel` that holds an `__init__.py`, "" for none: a
    file there ships with the code, a README aside."""
    if PurePosixPath(rel).stem.lower() == "readme":
        return ""
    parts = PurePosixPath(rel).parts[:-1]
    for n in range(len(parts), 0, -1):
        folder = "/".join(parts[:n])
        if (Path(root) / folder / "__init__.py").is_file():
            return folder
    return ""


def is_instruction(rel):
    """whether `rel` is a file a model reads as its instructions."""
    return briefing.watched(rel) or rel.split("/")[0] == "rules"


def place_refusal(root, rel, own):
    """-> why `rel`, a path from the place, is not the project's own file to
    hand as a doc, "" when it is."""
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
    """-> the docs of the place, instruction files first, then by path."""
    found = []
    for path in facts.walk(root, root, own):
        rel = facts.rel_of(root, path)
        if is_doc(rel) and not is_spec(rel) and not is_test(rel) \
                and not is_runners(rel) and not packaged(root, rel) \
                and not place_refusal(root, rel, own):
            found.append(rel)
    return sorted(found, key=lambda r: (not is_instruction(r), r))


def nearness(rel, files):
    """-> how near the doc `rel` sits to the nearest of `files`: the depth of
    its folder when that folder holds one of them, at any depth below, -1
    when it holds none."""
    folder = PurePosixPath(rel).parent.parts
    best = -1
    for f in files or ():
        if PurePosixPath(f).parent.parts[:len(folder)] == folder:
            best = max(best, len(folder))
    return best


def handed_docs(lines):
    """-> the docs `named` lines quote, in their order."""
    return [l[2:].split(" ", 1)[0] for l in lines
            if l.startswith("- ") and not l.startswith("- left out at the cap")]


def named(root, changed, names=(), own=None, docs=DOCS, chars=CHARS,
          near=False):
    """-> a line per doc of the place that names a file in `changed` or one
    of `names`, with the lines that name them, at most `docs` docs and
    `chars` characters; the docs left out at the cap are named on one line
    of at most `LEFT_LINE` characters, the rest counted. with `near`,
    what a step is handed: the doc nearest a file of `changed` first, beside
    it, then each folder up, then the rest, a doc that is one of `changed`
    left out (the step is handed it already), a file named only inside a
    longer name (`plan.md` in `budget-plan.md`) not taken for it, and a line
    that names a path on the machine is not quoted."""
    root = Path(root)
    terms = []
    for rel in changed or []:
        for term in (rel, PurePosixPath(rel).name):
            if term not in terms and (term == rel or "." in term):
                terms.append(term)
    words = [n for n in names or () if n not in terms]
    if not terms and not words:
        return []
    edge = (r"(?<![\w-])", r"(?![\w-])") if near else ("", "")
    pattern = re.compile("|".join(
        [edge[0] + re.escape(t) + edge[1] for t in terms]
        + [r"(?<![\w-])" + re.escape(w) + r"(?![\w-])" for w in words]))
    found = docs_in(root, own)
    if near:
        found.sort(key=lambda r: (-nearness(r, changed), not is_instruction(r),
                                  r))
    out, left, used, kept = [], [], 0, 0
    for rel in found:
        if near and rel in changed:
            continue
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
        block.extend("  " + rel + ":" + str(n) + ": " + (
            ON_MACHINE if near and factsguard.machine_path(l)
            else l.strip()[:LINE]) for n, l in hits)
        size = sum(len(b) + 1 for b in block)
        if kept >= docs or used + size > chars:
            left.append(rel)
            continue
        out.extend(block)
        used, kept = used + size, kept + 1
    if left:
        out.append(left_out(docs, chars, left))
    return out


def left_out(docs, chars, left):
    """-> the line naming the docs left out at the cap: as many as fit in
    `LEFT_LINE` characters, the rest counted."""
    head = ("- left out at the cap of " + str(docs) + " docs and "
            + str(chars) + " characters: ")
    shown = []
    for rel in left:
        rest = len(left) - len(shown) - 1
        line = head + ", ".join(shown + [rel]) + (
            " and " + str(rest) + " more" if rest else "")
        if len(line) > LEFT_LINE:
            break
        shown.append(rel)
    rest = len(left) - len(shown)
    if not shown:
        return head + str(rest) + " docs"
    return head + ", ".join(shown) + (" and " + str(rest) + " more"
                                      if rest else "")
