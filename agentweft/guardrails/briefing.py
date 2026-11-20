"""the files in a place that brief a model before the prompt does.

a model cli started in a directory can take what it finds there as
instructions or as its own config: a CLAUDE.md or AGENTS.md at any depth, the `.claude/`
directory, a `.mcp.json`. a step that writes one of those has written the
next step's instructions, and nothing in the prompt says so.

so the run takes a digest of them when it starts and compares before each step
that starts a model there. what is in the place at the start is what the person
pointed the run at; what turns up later came from a step.

a `claude` step loads the person's own settings only (`--setting-sources
user`): a place's settings files, hooks and `.mcp.json` start programs, and a
repo is not the person. so the cli no longer reads the place's instruction
files either, and the run hands the ones it read itself, as text: the root
CLAUDE.md, `.claude/CLAUDE.md` and every `.md` under `.claude/rules/`, as they
read when the run started (`handed`, `text`), in one file under the run's own
folder that every `claude` step is passed. the run's record keeps the digest
and that text (`kept`), and a leg that picks the run up takes them from there
(`carried`), never from the place as it is then.
"""
import hashlib
import os
from pathlib import Path

NAMES = ("claude.md", "claude.local.md", "agents.md", ".mcp.json")

FIRST = ("claude.md", ".claude/claude.md")
RULES = ".claude/rules/"
FOLDER = "brief"
FILE = "place.md"
HEAD = "the place's instruction files, as they read when the run started."
UNREAD = "unreadable: "


def watched(rel):
    parts = rel.split("/")
    # lower() because the place may be on a filesystem that does not care
    # about case, and the cli finds claude.md there as readily as CLAUDE.md
    return ".claude" in parts[:-1] or parts[-1].lower() in NAMES


def digest(where):
    """-> {path relative to the place: sha256 of what is in it}."""
    root = Path(where)
    out = {}
    for top, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            p = Path(top) / name
            rel = p.relative_to(root).as_posix()
            if not watched(rel):
                continue
            try:
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                out[rel] = "unreadable"
    return out


def changed(before, after):
    """-> the paths written, edited or removed between the two, sorted."""
    return sorted(p for p in set(before) | set(after)
                  if before.get(p) != after.get(p))


def handed(where, briefed):
    """-> [(path relative to the place, its text, None when it could not be
    read)] for the instruction files `digest` found that a `claude` step is
    handed: CLAUDE.md, then `.claude/CLAUDE.md`, then the rules by path. a
    file whose bytes are no longer the ones the digest hashed counts as not
    read: what is handed is what the run started on."""
    first = [r for name in FIRST for r in sorted(briefed)
             if r.lower() == name]
    rules = sorted(r for r in briefed
                   if r.startswith(RULES) and r.lower().endswith(".md"))
    out = []
    for rel in first + rules:
        try:
            raw = (Path(where) / rel).read_bytes()
        except OSError:
            raw = None
        if raw is not None and hashlib.sha256(raw).hexdigest() != briefed[rel]:
            raw = None
        out.append((rel, None if raw is None
                    else raw.decode("utf-8", "replace")))
    return out


def kept(briefed, files):
    """-> what the run's record keeps of its first start: the digest and the
    text handed, so a leg that picks it up hands the same (`carried`)."""
    return {"digest": dict(briefed),
            "files": [[rel, said] for rel, said in files]}


def carried(said):
    """-> (the digest, the files handed, "") a record kept (`kept`); (None,
    None, "") for a record that kept none, written before it was kept; ({},
    [], why) for one that cannot be read: nothing is handed and every
    instruction file in the place counts as changed."""
    if said is None:
        return None, None, ""
    try:
        digest, files = said["digest"], said["files"]
        if not isinstance(digest, dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in digest.items()):
            raise ValueError("its digest is not in the form written")
        if not isinstance(files, list) or not all(
                isinstance(f, list) and len(f) == 2 and isinstance(f[0], str)
                and (f[1] is None or isinstance(f[1], str)) for f in files):
            raise ValueError("its files are not in the form written")
    except (KeyError, TypeError, ValueError) as e:
        return {}, [], ("the brief the run started on could not be read ("
                        + str(e) + "), so nothing is handed and every"
                        " instruction file in the place counts as changed")
    return dict(digest), [(rel, text) for rel, text in files], ""


def text(files):
    """-> the brief a `claude` step is passed, each file under its path."""
    out = [HEAD]
    for rel, said in files:
        out.append("## " + rel)
        out.append(UNREAD + rel if said is None else said.rstrip("\n"))
    return "\n\n".join(out) + "\n"


def write(folder, files):
    """-> the brief file written under the run's `folder`, None when there is
    nothing to hand."""
    if not files:
        return None
    path = Path(folder) / FOLDER / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text(files).encode("utf-8"))
    return path
