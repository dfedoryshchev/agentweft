"""a run that works in a checkout of its own instead of the person's tree.

`--worktree` on the command line, or `worktree: true` in the flow, makes the
run add a detached `git worktree` of HEAD under runs/worktrees/<run id> and
work there: every step, every gate, the start snapshot and the changed-file
record read that checkout and never the tree the person is working in. a
commit to start from may be named instead of HEAD (`--worktree <commit>`, or
`worktree: <commit>`). loose changes in the person's tree are not carried
over: the run starts from a commit, so what it found is something git holds.

the checkout is left where it is at the end, for the person to read and to
bring back. the handoff names it and the commands for both. a resume carries
on in the same one. `python run.py worktree` lists them, and
`python run.py worktree remove <run id>` removes one, refusing while it holds
work nothing else has: a file not committed, or a commit no branch holds.
"""
import json
import sys
from pathlib import Path

from agentweft.guardrails import worktree

from . import state
from .config import where

FLAG = "--worktree"
FOLDER = "worktrees"


def asked(fm, argv):
    """-> the commit a new run's checkout is made from, or None when the run
    works where it is. the flag beats the flow's key."""
    if FLAG in argv:
        i = argv.index(FLAG)
        said = argv[i + 1].strip() if len(argv) > i + 1 else ""
        return "HEAD" if not said or said.startswith("-") else said
    said = fm.get("worktree")
    if said is True:
        return "HEAD"
    if isinstance(said, str) and said.strip():
        return said.strip()
    return None


def make(fm, named, run_id, base):
    """-> (the run's place inside a new checkout, what the manifest keeps of
    it). raises ValueError the way `where` does."""
    place = where(fm, named)
    path = state.RUNS / FOLDER / run_id
    inside, sha, top = worktree.for_run(place, path, base)
    return inside, {"path": str(path.resolve()), "base": sha,
                    "repo": str(top), "asked": base}


def discard(made):
    """remove a checkout the run made and did not get to use."""
    if made:
        worktree.remove(made["repo"], made["path"])


def lines(made, run_id):
    """-> the handoff's lines on the run's checkout, [] when it had none."""
    if not made:
        return []
    path, base = made["path"], made["base"]
    branch = "agentweft/" + run_id
    return ["",
            "## worktree",
            "- the run worked in " + path + ", made from " + base[:12]
            + "; the tree it was started from was not touched.",
            "- to bring the change back, commit it on a branch there and merge"
            " that branch where you work:",
            "  git -C " + path + " switch -c " + branch,
            "  git -C " + path + " add -A",
            "  git -C " + path + " commit",
            "  git merge " + branch,
            "- or take it as a patch: git -C " + path + " diff " + base[:12],
            "  (files the run added show there once they are added with"
            " `git -C " + path + " add -A`)",
            "- to remove it: python run.py worktree remove " + run_id
            + " (it refuses while the worktree holds work no branch has;"
            " --force removes it anyway)"]


def headline(made):
    """-> the one line the top of the handoff gives it, "" for none."""
    if not made:
        return ""
    return "worktree: " + made["path"] + " (from " + made["base"][:12] + ")."


def kept():
    """-> [(run id, what its manifest keeps of its checkout)], one per
    checkout still on disk or still in a manifest, newest run last."""
    out = {}
    root = state.RUNS
    if not root.is_dir():
        return []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            data = json.loads((folder / "manifest.json").read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            continue
        made = data.get("worktree") if isinstance(data, dict) else None
        if made and made.get("path"):
            out[made["path"]] = (folder.name, made)
    return sorted(out.values(), key=lambda pair: pair[0])


def find(run_id):
    """-> what the run's manifest keeps of its checkout, whether the run
    named made it or carried on in it."""
    for name, made in kept():
        if name == run_id or Path(made["path"]).name == run_id:
            return made
    return None


def cmd(argv=None):
    """python run.py worktree [remove <run id> [--force]]"""
    argv = list(sys.argv if argv is None else argv)
    rest = argv[2:]
    if not rest:
        found = kept()
        if not found:
            print("no run has a worktree of its own")
            return 0
        for name, made in found:
            there = Path(made["path"]).exists()
            print(name + "  " + made["path"] + ("" if there else "  (gone)"))
        return 0
    if rest[0] != "remove" or len(rest) < 2:
        print("usage: python run.py worktree [remove <run id> [--force]]")
        return 1
    run_id = rest[1]
    made = find(run_id)
    if made is None:
        print("no worktree kept for " + run_id)
        return 1
    try:
        left = worktree.drop(made["repo"], made["path"], made["base"],
                             force="--force" in rest)
    except ValueError as e:
        print(str(e))
        return 1
    if left:
        print(made["path"] + " holds work that would be lost, so it is kept:")
        for line in left:
            print("  " + line)
        print("commit it on a branch, or add --force to remove it anyway")
        return 1
    print("removed " + made["path"])
    return 0
