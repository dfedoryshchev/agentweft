"""the files in a place that brief a model before the prompt does.

a model cli started in a directory can take what it finds there as
instructions or as its own config: a CLAUDE.md or AGENTS.md at any depth, the `.claude/`
directory, a `.mcp.json`. a step that writes one of those has written the
next step's instructions, and nothing in the prompt says so.

so the run takes a digest of them when it starts and compares before each step
that starts a model there. what is in the place at the start is what the person
pointed the run at; what turns up later came from a step.
"""
import hashlib
import os
from pathlib import Path

NAMES = ("claude.md", "claude.local.md", "agents.md", ".mcp.json")


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
