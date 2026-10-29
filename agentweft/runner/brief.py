"""what the steps so far found, kept by the run for the steps after it.

each step starts in a fresh session. the handoff told the next step which
files were read and not what they said, so it opened them again: the spec,
the code, the tests, every step, paid for each time. the brief carries the
lines themselves. every READ and MUST NOT MISS line naming `path:lines` is
quoted from the place, and every claim its step's transcript backs is kept
with its command; a claim nothing checked is not handed on as a fact.

a step gets the brief of the steps before it in the flow's order, not the
whole run: a step asked again with nothing new above it gets the same prompt,
and the same prompt inside one run is still the same answer.

the brief is capped. what does not fit is named, so a step knows to open it.
the run keeps the whole of it as `brief.md` in its folder.

a step is also handed the project's facts (`orchestrate/facts.py`) for the
files it is handed, first in its brief and under a cap of their own: each
with its why, its source and its anchored lines as the place has them now,
the live ones first and the stale ones marked.
"""
import re
import subprocess
import threading
from pathlib import Path

FILE = "brief.md"
# about 2k tokens: past that a brief is an overview, and overviews were
# measured to add cost without adding fixes
CAP = 8000
QUOTE_LINES = 12
LINE_WIDTH = 200
RESERVE = 400
# about 500 tokens of the brief's cap: a fact is the non-obvious way of one
# place, and more of them than this reads as an overview
FACTS_CAP = 2000
FACTS_HEAD = ("facts for the files you are handed, kept by the runner across"
              " runs: what this project decided about them and why. hold to"
              " them; a change that departs from one says so and why on a"
              " DECIDED or DOUBTS line.")
NONE_YET = "(the brief is empty: no step before you handed one over in this run)"

CREDENTIAL = re.compile(r"^(\.env(\..*)?|\.netrc|\.pypirc|id_[^.]+"
                        r"|.*\.(pem|key))$", re.IGNORECASE)

WHERE = re.compile(r"^`?(?P<path>[^`\s]+?):(?P<a>\d+)(?:\s*-\s*(?P<b>\d+))?`?"
                   r"(?:\s+-+\s+|\s*:\s+|\s+|$)(?P<note>.*)$")


def where_of(item):
    """-> (path, first, last, note) for a `path:lines - note` line, or None
    when it names no lines."""
    m = WHERE.match(item.strip())
    if not m:
        return None
    first = int(m.group("a"))
    last = int(m.group("b")) if m.group("b") else first
    if last < first:
        first, last = last, first
    return m.group("path"), first, last, m.group("note").strip()


def named_in(items):
    """-> the paths `items` name, in the order first named."""
    from agentweft.mcp.preflight import files_mentioned

    out = []
    for item in items:
        text = item if isinstance(item, str) else str(item)
        found = where_of(text)
        names = [found[0].replace("\\", "/")] if found else []
        names.extend(sorted(files_mentioned(text)))
        out.extend(n for n in names if n not in out)
    return out


def untracked(where):
    """-> (the top of the repo, the paths under it git does not track in
    `where` now, ignored ones included, a folder ending in `/`), or None
    when `where` is not in a git work tree."""
    if where is None:
        return None
    from agentweft.guardrails import fence

    try:
        return fence.untracked(where)
    except (ValueError, OSError):
        return None


def ignored(top, rel):
    """whether git ignores `rel` under `top` now. an answer git could not
    give counts as ignored."""
    try:
        done = subprocess.run(["git", "-C", str(top), "check-ignore", "-q",
                               "--", rel], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return True
    return done.returncode != 1


class Brief(object):

    def __init__(self, where, order=()):
        self.where = Path(where) if where else None
        self.order = list(order)
        self.goes = {}
        self.lock = threading.RLock()
        self.loose = untracked(self.where)

    def quotable(self, target):
        """whether the brief may quote `target`: a file git tracks or one
        the run made outside a folder git did not track. one that was there
        untracked when the run started, one git ignores when it is quoted,
        an ignored `.env` above all, or one inside an ignored folder, is
        named and never quoted: the brief goes into every later prompt and
        onto disk. outside git nothing says which is which: every file is
        quoted but one named like a credential."""
        if self.loose is None:
            return not CREDENTIAL.match(target.name)
        top, found = self.loose
        try:
            rel = target.relative_to(top).as_posix()
        except ValueError:
            return False
        if any(rel == p or (p.endswith("/") and rel.startswith(p))
               for p in found):
            return False
        return not ignored(top, rel)

    def add(self, step, task, role, block):
        """what one go of `step` handed over. a later go of the same step and
        task replaces it: what a step said before it was sent back may be
        what it was sent back for."""
        if not block or block.get("state") not in ("present", "partial"):
            return
        found = {"rules": [], "facts": [], "read": []}
        for item in block.get("must_not_miss", []):
            found["rules"].append((role, item))
        did = block.get("did") or []
        if did:
            found["facts"].append((role, role + " did: " + did[0]))
        for v in block.get("verified", []):
            if v.get("backed") != "backed" or not v.get("claim"):
                continue
            line = v["claim"]
            if v.get("cmd"):
                line = line + ", checked with: " + v["cmd"]
            found["facts"].append((role, line))
        for item in block.get("read", []):
            found["read"].append((role, item))
        found["paths"] = named_in(list(block.get("must_not_miss", []))
                                  + list(did) + list(block.get("read", [])))
        with self.lock:
            self.goes[(step, task)] = found

    def entries(self, before=None):
        """-> (rules, facts, read) of every step before `before` in the
        flow's order, or of every step when `before` is None."""
        with self.lock:
            goes = list(self.goes.items())
        rank = dict((s, n) for n, s in enumerate(self.order))
        limit = rank.get(before, len(self.order)) if before else None
        goes.sort(key=lambda kv: (rank.get(kv[0][0], len(self.order)),
                                  kv[0][1] or 0))
        out = {"rules": [], "facts": [], "read": []}
        for (step, _), found in goes:
            if limit is not None and rank.get(step, len(self.order)) >= limit:
                continue
            for key in out:
                for entry in found[key]:
                    if entry[1] not in [e[1] for e in out[key]]:
                        out[key].append(entry)
        return out["rules"], out["facts"], out["read"]

    def paths(self, before=None):
        """-> every path the MUST NOT MISS, DID and READ lines of the steps
        before `before` name, in the order first named."""
        with self.lock:
            goes = list(self.goes.items())
        rank = dict((s, n) for n, s in enumerate(self.order))
        limit = rank.get(before, len(self.order)) if before else None
        out = []
        for (step, _), found in goes:
            if limit is not None and rank.get(step, len(self.order)) >= limit:
                continue
            out.extend(p for p in found.get("paths", []) if p not in out)
        return out

    def key(self, before=None, handed=()):
        """-> what the brief for `before` holds, without the lines it quotes
        from the place: the facts handed are keyed by id and status."""
        said = [(f.id, f.status) for f in handed]
        return repr(self.entries(before)) + (repr(said) if said else "")

    def quote(self, path, first, last):
        """-> the lines as the place has them now, numbered, or [] for a
        file outside the place or not there."""
        if self.where is None:
            return []
        root = self.where.resolve()
        try:
            target = (root / path.replace("\\", "/")).resolve()
            target.relative_to(root)
        except (ValueError, OSError):
            return []
        if not target.is_file() or not self.quotable(target):
            return []
        try:
            lines = target.read_text(encoding="utf-8",
                                     errors="replace").split("\n")
        except OSError:
            return []
        stop = min(last, first + QUOTE_LINES - 1, len(lines))
        out = ["    " + str(n) + ": " + lines[n - 1][:LINE_WIDTH]
               for n in range(first, stop + 1)]
        if out and stop < last:
            out.append("    (" + str(last - stop) + " more lines not quoted)")
        return out

    def chunk(self, role, item):
        out = ["- " + item + " (from " + role + ")"]
        found = where_of(item)
        if found:
            out.extend(self.quote(*found[:3]))
        return "\n".join(out)

    def kept_facts(self, handed):
        """-> the lines of the facts section for `handed`, under FACTS_CAP,
        [] for none. what does not fit is named with the file it is in."""
        shown, left = self.fit(handed)
        if not shown and not left:
            return []
        out = [FACTS_HEAD] + [piece for _, piece in shown]
        if left:
            out.append(str(len(left)) + " more left out at the size cap; open"
                       " them yourself if you need them: " + ", ".join(
                           f.id + " (" + self.facts_file(f) + ")"
                           for f in left))
        return out

    def fit(self, handed):
        """-> ([(fact, its text)] that fit under FACTS_CAP, [the facts that
        do not])."""
        shown, left, size = [], [], len(FACTS_HEAD)
        for fact in handed or ():
            piece = self.fact_chunk(fact)
            if size + len(piece) + 1 > FACTS_CAP:
                left.append(fact)
                continue
            shown.append((fact, piece))
            size = size + len(piece) + 1
        return shown, left

    def facts_file(self, fact):
        if fact.file is None or self.where is None:
            return "facts/"
        try:
            return Path(fact.file).resolve().relative_to(
                self.where.resolve()).as_posix()
        except ValueError:
            return "facts/"

    def fact_chunk(self, fact):
        """-> one fact as a step reads it: id, scope, kind and label, the
        claim, its why and source, and its anchored lines when it is live."""
        from agentweft.orchestrate import facts

        what = ", ".join([fact.kind or "fact"] + ([fact.label]
                         if fact.label and fact.label != "none" else []))
        head = "- " + fact.id + " " + ", ".join(fact.scopes) + " (" + what + ")"
        if fact.status == facts.STALE:
            said = fact.get("stale").split(" ", 1)
            head = (head + ", possibly stale" + (", " + said[1] if len(said) > 1
                                                  else "")
                    + (" (" + said[0] + ")" if said[0] else ""))
        out = [head + ": " + fact.claim, "  why: " + fact.why]
        if fact.get("source"):
            out.append("  source: " + fact.get("source"))
        if fact.get("unchecked"):
            out.append("  unchecked: " + fact.get("unchecked"))
        at = facts.anchor_of(fact)
        if at is not None and fact.status == facts.LIVE:
            out.extend(self.quote(at.path, at.first, at.last))
        return "\n".join(out)

    def text(self, before=None, handed=()):
        """-> the brief for the step `before`, or the whole of it, under
        CAP characters; "" when there is nothing in it. `handed` is the
        project's facts for the files the step is handed, nearest first."""
        rules, facts, read = self.entries(before)
        kept = self.kept_facts(handed)
        if not (rules or facts or read):
            return "\n".join(kept)[:CAP]
        out = ["what the steps before you found. the lines are quoted from"
               " the place as it is now."]
        size = len(out[0])
        if kept:
            size = size + len("\n".join(kept)) + 2
            out = kept + [""] + out
        left = []
        for title, entries in (("rules the work is held to:", rules),
                               ("facts already established:", facts),
                               ("lines already read:", read)):
            shown = []
            for role, item in entries:
                piece = self.chunk(role, item)
                extra = len(piece) + 1 + (len(title) + 2 if not shown else 0)
                if size + extra > CAP - RESERVE:
                    left.append(item.split(" ")[0])
                    continue
                shown.append(piece)
                size = size + extra
            if shown:
                out.append("")
                out.append(title)
                out.extend(shown)
        if left:
            tail = (str(len(left)) + " more left out at the size cap; open"
                    " them yourself if you need them: " + ", ".join(left))
            room = CAP - size - 3
            if len(tail) > room:
                tail = tail[:max(0, room - 4)].rstrip(", ") + " ..."
            out.append("")
            out.append(tail)
        return "\n".join(out)[:CAP]

    def save(self, folder):
        with self.lock:
            text = self.text()
            if not text:
                return None
            path = Path(folder) / FILE
            path.write_text(text + "\n", encoding="utf-8")
        return path
