"""what a run hands to a person: runs/<run id>/handoff.md, on every end.

finished, parked, a failed gate, the budget, an outage, a crash: each leaves
the same file, and it is the last thing the run prints. it answers what the
person asks, in the order they ask it: what came of it, what they have to do,
what the steps assumed and doubt, what changed, what was tested and how, what
a ruling is owed on, what was not verified, what the next session must keep,
and what the run was.

two kinds of line go into it and they are kept apart. what the steps said
comes from their HANDOFF blocks and their labelled lines, under the step's
own name. what the runner knows - the files that changed, the commits, the
gate results and their commands, the red-first proof, the rulings on record,
the spend - comes from git, the gate record and the budget, and never from a
step's text. a claim a step made about a command is marked with whether its
transcript shows it.

this is the one writer of handoff.md. `orchestrate/park.py` contributes the
"needs you" section when the run is waiting for someone.
"""
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from agentweft.flow.spec import step_id
from agentweft.guardrails.snapshot import TEST_PATH, is_test  # noqa: F401
from agentweft.guardrails.snapshot import is_spec as spec_path
from agentweft.guardrails import skips, specfiles

from . import (front, handoff, investigate, lead, leftred, manifest, ruling,
               stops, trace, verbs, wouldpass)

FILE = "handoff.md"

JUDGING = ("reviewer", "verify", "judge")

AUTHORITY = re.compile(r"\b(user-directed|user-approved|session-settled"
                       r"|as agreed|as discussed|per the user|the user wants"
                       r"|the (?:user|lead|owner|maintainer|reviewer|team)"
                       r" (?:has |had )?(?:approved|ruled|agreed|decided))\b",
                       re.I)
NEGATED = re.compile(r"\b(not|never|no|nobody|without)\W+(\w+\W+){0,2}$",
                     re.I)


def _git(place, *args):
    try:
        r = subprocess.run(["git", "-C", str(place)] + list(args),
                           capture_output=True, encoding="utf-8",
                           errors="replace")
    except (FileNotFoundError, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def cause(line):
    """`CAUSE: <where> - <why>` as a sentence that starts in lower case."""
    return "cause" + line[5:] if line.upper().startswith("CAUSE") else line


def did_of(passes, role):
    """every DID line the role handed over, first pass first, no repeats:
    a step sent back and run again did its work in two accounts."""
    out = []
    for p in passes:
        if p["role"] == role and _present(p["block"]):
            out.extend(i for i in p["block"]["did"] if i not in out)
    return out


def is_spec(path, root=None, place=None):
    """whether a path from the top of the repo is a spec file, read from the
    top of the place (`snapshot.is_spec`)."""
    if root is not None and place is not None:
        try:
            path = (Path(root) / path).resolve().relative_to(
                Path(place).resolve()).as_posix()
        except ValueError:
            return False
    return spec_path(path)


def _numstat(text):
    out = []
    for line in (text or "").split("\n"):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a = int(parts[0]) if parts[0].isdigit() else 0
        d = int(parts[1]) if parts[1].isdigit() else 0
        out.append((parts[-1], a, d))
    return out


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _unquote(path):
    path = path.strip()
    if len(path) > 1 and path[0] == path[-1] == '"':
        path = path[1:-1]
    return path


def _ranges(text):
    """-> {path: "2, 5-7"} for a `git diff --unified=0`: the lines each file
    holds now that the diff added or changed, and where lines were only
    taken out."""
    out = {}
    path = None
    old = None
    for line in (text or "").split("\n"):
        if line.startswith("--- "):
            old = _unquote(line[4:])
            old = old[2:] if old.startswith("a/") else old
        elif line.startswith("+++ "):
            new = _unquote(line[4:])
            path = new[2:] if new.startswith("b/") else old
            out.setdefault(path, [])
        elif path is not None:
            m = HUNK.match(line)
            if not m:
                continue
            first = int(m.group(1))
            many = 1 if m.group(2) is None else int(m.group(2))
            if many == 0:
                out[path].append("removed after " + str(first))
            elif many == 1:
                out[path].append(str(first))
            else:
                out[path].append(str(first) + "-" + str(first + many - 1))
    return dict((p, ", ".join(r)) for p, r in out.items())


NAME = re.compile(r"[A-Za-z_]\w*")


def _touched(text):
    """-> {path: [name]} for a `git diff --unified=0`: the names on the lines
    each file's change adds or takes out, and in the function git prints on
    each hunk's header."""
    out = {}
    path = None
    old = None
    for line in (text or "").split("\n"):
        if line.startswith("--- "):
            old = _unquote(line[4:])
            old = old[2:] if old.startswith("a/") else old
        elif line.startswith("+++ "):
            new = _unquote(line[4:])
            path = new[2:] if new.startswith("b/") else old
            out.setdefault(path, set())
        elif path is not None and HUNK.match(line):
            out[path].update(NAME.findall(line.split("@@", 2)[-1]))
        elif path is not None and line[:1] in ("+", "-"):
            out[path].update(NAME.findall(line[1:]))
    return out


def _lines(text):
    return [l.rstrip() for l in (text or "").split("\n") if l.strip()]


def _porcelain(place):
    """-> [(the two status letters, the path now)], each path as it is on
    disk: `-z` leaves a name with a space or a non-ASCII letter unquoted."""
    out = []
    entries = iter((_git(place, "status", "--porcelain", "-z",
                         "--untracked-files=all", "--", ".") or "").split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        out.append((entry[:2], entry[3:]))
        if entry[0] in "RC":
            next(entries, None)
    return out


class Tree(object):
    """the state of the place when the run started, kept to tell what the
    run changed from what was already there."""

    __slots__ = ("place", "git", "root", "start", "dirty")

    def __init__(self, place):
        self.place = Path(place)
        self.git = False
        self.root = None
        self.start = None
        self.dirty = set()
        top = _git(place, "rev-parse", "--show-toplevel")
        if top is None:
            return
        self.git = True
        self.root = Path(top.strip())
        head = _git(place, "rev-parse", "--verify", "--quiet", "HEAD")
        self.start = head.strip() if head else None
        self.dirty = set(p for _, p in _porcelain(place))

    def changes(self):
        """-> what is different now, from git: commits since the start, each
        file with its line counts and whether it is committed, uncommitted or
        untracked, and the test and spec files among them. `ranges` holds
        the lines each file's change covers, by (path, how), and `names` the
        names the change touches in each file (`_touched`; every name in an
        untracked one); `status` and `log` are what `git status --short` and
        `git log --oneline <start>..HEAD` print, line for line."""
        out = {"git": self.git, "start": self.start, "commits": [],
               "files": [], "tests_changed": [], "spec_changed": [],
               "ranges": {}, "names": {}, "status": [], "log": []}
        names = {}
        if not self.git:
            return out
        out["status"] = _lines(_git(self.place, "-c", "core.quotepath=false",
                                    "status", "--short",
                                    "--untracked-files=all", "--", "."))
        if self.start:
            out["log"] = _lines(_git(self.place, "log", "--oneline",
                                     "--no-decorate", self.start + "..HEAD"))
            for line in (_git(self.place, "log", "--format=%h%x09%s",
                              self.start + "..HEAD") or "").split("\n"):
                if "\t" in line:
                    sha, subject = line.split("\t", 1)
                    out["commits"].append((sha, subject))
            for kind, args in (("committed", (self.start, "HEAD")),
                               ("uncommitted", ("HEAD",))):
                diff = _git(self.place, "-c", "core.quotepath=false",
                            "diff", "--unified=0", "--no-color",
                            "--no-ext-diff", *(args + ("--", ".")))
                for path, span in _ranges(diff).items():
                    out["ranges"][(path, kind)] = span
                for path, found in _touched(diff).items():
                    names.setdefault(path, set()).update(found)
        committed = _numstat(_git(self.place, "diff", "--numstat",
                                  self.start, "HEAD", "--", ".")
                             if self.start else "")
        uncommitted = _numstat(_git(self.place, "diff", "--numstat", "HEAD",
                                    "--", ".") if self.start else "")
        untracked = []
        for code, path in _porcelain(self.place):
            if code != "??":
                continue
            try:
                body = (self.root / path).read_bytes()
            except OSError:
                body = b""
            lines = body.count(b"\n")
            names.setdefault(path, set()).update(
                NAME.findall(body.decode("utf-8", "replace")))
            untracked.append((path, lines, 0))
            if lines:
                out["ranges"][(path, "untracked")] = (
                    "1" if lines == 1 else "1-" + str(lines))
        for kind, found in (("committed", committed),
                            ("uncommitted", uncommitted),
                            ("untracked", untracked)):
            for path, a, d in found:
                how = kind
                if kind != "committed" and path in self.dirty:
                    how = kind + ", already modified before the run"
                out["files"].append((path, a, d, how))
                if kind == "untracked":
                    continue
                if is_test(path):
                    out["tests_changed"].append((path, a, d))
                if is_spec(path, self.root, self.place):
                    out["spec_changed"].append((path, a, d))
        out["names"] = dict((p, sorted(n)) for p, n in names.items())
        return out


def tree(place):
    return Tree(place)


def _names(decision):
    return (decision.decided + "\n" + decision.why).lower()


def _ruling_for(path, decided):
    """-> the decision that names this path, by its path or its file name."""
    name = path.rsplit("/", 1)[-1].lower()
    for d in decided:
        if path.lower() in _names(d) or name in _names(d):
            return d
    return None


def stamp(d):
    return d.at.strftime(stops.STAMP) + " " + d.decided


def rulings(changes, decided, spec_files=None):
    """the lines a person owes a ruling on, or that one already covers.

    a pre-existing test whose lines were removed or changed, and a spec file
    (`TASK.md`, `SPEC*.md` or under `docs/spec*`, from the top of the
    place) changed at all, each name
    the decisions.md entry behind them or say UNRULED. an add-only test
    change needs none and says so, and so does a spec file with lines added
    and none removed when `spec_files` is `additions`, the flow's rule that
    allows exactly that.
    """
    out = []
    for path, a, d in changes.get("tests_changed", []):
        line = "- pre-existing test " + path + " +" + str(a) + " -" + str(d)
        if d == 0:
            out.append(line + ", add-only, no ruling needed")
            continue
        found = _ruling_for(path, decided)
        out.append(line + (" <- ruling " + stamp(found) if found else
                           " <- UNRULED: lines removed or changed, and no"
                           " entry in decisions.md names it"))
    for path, a, d in changes.get("spec_changed", []):
        line = "- spec " + path + " +" + str(a) + " -" + str(d)
        if d == 0 and spec_files == specfiles.ADDITIONS:
            out.append(line + ", lines added only, which spec_files: "
                       + specfiles.ADDITIONS + " allows, no ruling needed")
            continue
        found = _ruling_for(path, decided)
        out.append(line
                   + (" <- ruling " + stamp(found) if found else
                      " <- UNRULED: the spec text changed, and no entry in"
                      " decisions.md names it"))
    return out


def authority(blocks, decided_in_run):
    """a step that claims an agreement, an approval or a ruling with none on
    record in this run. `blocks` is [(role, block)]."""
    if decided_in_run:
        return []
    out = []
    for role, block in blocks:
        if block.get("state") not in (handoff.PRESENT, handoff.PARTIAL):
            continue
        for _, key in handoff.SECTIONS:
            for item in block.get(key) or []:
                text = item["claim"] if isinstance(item, dict) else item
                m = AUTHORITY.search(text)
                if m and not NEGATED.search(text[:m.start()]):
                    out.append(role + ': "' + m.group(1) + '" - ' + text)
    return out


def gate_commands(fm, step, output):
    """-> the command behind each gate the flow declares on `step`, in
    declaration order, "" for a gate that runs nothing."""
    from agentweft.guardrails.gates.redtest_gate import named_test

    for s in fm.steps:
        if step_id(s) != step:
            continue
        out = []
        for g in (s.get("gates") or []):
            cmd = g.get("command")
            if isinstance(cmd, (list, tuple)) and g.get("gate") == "red-first":
                # it runs every new test, so no one name stands for it
                cmd = " ".join(str(a) for a in cmd)
            elif isinstance(cmd, (list, tuple)):
                named = named_test(output or "")
                cmd = " ".join(named if a == "{test}" and named else str(a)
                               for a in cmd)
            out.append(cmd if isinstance(cmd, str) else "")
        return out
    return []


def gate_names(fm, step):
    """-> the name of each gate the flow declares on `step`, in declaration
    order, the order gate_commands keeps."""
    for s in fm.steps:
        if step_id(s) == step:
            return [g.get("gate") for g in (s.get("gates") or [])]
    return []


def _gates(results, commands, names):
    """-> each result kept with the command of the gate it came from: the
    nth result of a gate name gets the nth declared gate of that name's
    command, and a check the runner made itself gets none."""
    out = []
    taken = {}
    for g in results or []:
        if isinstance(g, dict):
            gate, ok, detail = g.get("gate"), g.get("ok"), g.get("detail")
            unsure = g.get("unproven") or []
            tests = g.get("tests")
            skipped = g.get("skipped")
            issue = g.get("issue")
        else:
            gate, ok, detail = g.gate, g.ok, g.detail
            unsure = g.unproven
            tests = getattr(g, "tests", None)
            skipped = getattr(g, "skipped", False)
            issue = trace.issue_of(g)
        nth = taken.get(gate, 0)
        taken[gate] = nth + 1
        at = [i for i, name in enumerate(names) if name == gate]
        kept = {"gate": gate, "ok": bool(ok), "detail": detail or "",
                "command": commands[at[nth]] if nth < len(at)
                and at[nth] < len(commands) else "",
                "tests": tests, "skipped": bool(skipped)}
        if unsure:
            kept["unproven"] = list(unsure)
        if issue:
            kept["issue"] = issue
        out.append(kept)
    return out


def unproven(passes):
    """-> (step, line) for every check a passing gate recorded as unproven,
    once each when a step sent back ran again and said the same."""
    out = []
    for p in passes:
        for g in p["gates"]:
            for line in (g.get("unproven", []) if g["ok"] else []):
                if (at(p), line) not in out:
                    out.append((at(p), line))
    return out


def outcome(stopped, unsure=()):
    """-> the run's one outcome (`stops.OUTCOMES`, or `done` with the count
    of checks nobody could decide)."""
    if stopped:
        return stops.outcome(stopped["cause"])
    return stops.done(len(unsure))


def redo_why(said):
    for line in handoff.without(said or "").split("\n"):
        if line.strip() and not line.strip().upper().startswith("VERDICT:"):
            return line.strip()
    return ""


def a_pass(step, role, seconds, block, gates, ungated, outcome, said,
           facts=None, writes=""):
    """one pass of one step, the shape `build` reads. `facts` is what its
    steps.jsonl line holds for the retro and the files its transcript shows
    it read (`facts_of`); `writes` is what the flow says the step writes
    (`writes_of`). `ruled` is the step's own DECIDED line, "" for none, and
    `would` its WOULD PASS and CATCH lines (`wouldpass.read`)."""
    return {"step": step, "role": role, "seconds": seconds, "writes": writes,
            "block": block if isinstance(block, dict) else handoff.empty(),
            "gates": gates, "ungated": ungated, "outcome": outcome,
            "verbs": verbs.parse(said), "ruled": lead.read(said)[0] or "",
            "would": wouldpass.read(said),
            "redo_why": redo_why(said) if outcome == "redo" else "",
            "facts": facts or {}}


RETRO = ("cost", "cost_from", "cached", "retries", "background_killed",
         "shell_writes_denied", "shell_trap_recoveries", "won", "fallback",
         "thinking", "effort")


def fallen(passes):
    """-> a line for each pass another model answered after the provider's
    fallback, and what the runner held back of it, if anything."""
    out = []
    for p in passes:
        fell = (p.get("facts") or {}).get("fallback")
        if isinstance(fell, dict) and fell.get("answered_by"):
            out.append("- " + trace.switched_said(at(p), fell)
                       + ("; " + fell["held"] if fell.get("held") else ""))
    return out


def read_of(sessions, root=None, earlier=None):
    """-> [(path, range)] the sessions' transcripts show read, None when not
    one of them has a transcript. `earlier` is the session a carried-on pass
    went on from, whose reads are not this pass's."""
    out = None
    for session in sessions:
        found = handoff.reads(session, root, earlier)
        if found is not None:
            out = (out or []) + found
    return out


def facts_of(line, root=None):
    """-> a pass's facts from its steps.jsonl line: the retro's fields, and
    what its sessions read, from `root` when the path is under it."""
    out = dict((k, line.get(k)) for k in RETRO)
    if out["won"] is None:
        out["won"] = trace.won(line.get("outcome"), line.get("cause"),
                               line.get("gates"), line.get("to"))
    sessions = [line["session"]] if line.get("session") else []
    sessions.extend(t["session"] for t in (line.get("tasks") or [])
                    if isinstance(t, dict) and t.get("session"))
    out["read"] = read_of(sessions, root, line.get("continued"))
    out["conformance"] = line.get("conformance") or []
    out["checked"] = line.get("checked")
    out["prevented"] = [g.get("gate") or "a gate" for g in line.get("gates")
                        or [] if isinstance(g, dict) and g.get("prevented")]
    if line.get("prevented"):
        out["prevented"].append("police")
    kept = line.get("facts")
    out["kept_facts"] = kept if isinstance(kept, dict) else None
    return out


def checked(passes):
    """-> (pass, line) for every fact check a pass's change set off, in
    the order they ran."""
    return [(p, c) for p in passes
            for c in (p.get("facts") or {}).get("conformance") or []]


def check_left(passes):
    """-> the view's lines for each fact whose last check in the run did
    not hold: broken, or could not run."""
    last = {}
    for p, c in checked(passes):
        last[c.get("fact")] = (p, c)
    out = []
    for p, c in last.values():
        where = c.get("fact", "") + " on " + ", ".join(c.get("scope") or [])
        if c.get("result") == "broken":
            out.append(where + ", broken by " + at(p) + ": "
                       + c.get("claim", ""))
        elif c.get("result") == "could not run":
            out.append(where + ", its check could not run after " + at(p)
                       + ": " + c.get("said", ""))
    return out


def passes_of(folder, roles, fm):
    """-> the passes of every leg up to a run folder, first leg first, for a
    run that picks it up. with more than one leg, each pass carries the
    number of its leg; a leg whose folder is gone is one pass that says so."""
    folders, gone = manifest.legs(folder)
    out = []
    if gone:
        out.append(dict(a_pass(gone, gone, 0, handoff.empty(
            handoff.UNREADABLE, why="its run folder is gone, so that leg and"
            " any before it are not read"), [], None, "", ""), leg=1))
    for n, leg in enumerate(folders, len(out) + 1):
        for p in _passes_in(leg, roles, fm):
            if gone or len(folders) > 1:
                p["leg"] = n
            p["run"] = leg.name
            out.append(p)
    return out


def at(p):
    """-> where a pass ran: its step, and its leg when it came from one."""
    return p["step"] + (" in leg " + str(p["leg"]) if p.get("leg") else "")


def _passes_in(folder, roles, fm):
    out = []
    path = folder / "steps.jsonl"
    if not path.exists():
        return out
    root = None
    if (folder / "workdir").is_file():
        root = (folder / "workdir").read_text(encoding="utf-8").strip() or None
    seqs = []
    for raw in path.read_text(encoding="utf-8").split("\n"):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if line.get("outcome") == trace.WARM:
            continue
        out.append(line_pass(line, folder, roles, fm, root))
        seqs.append(line.get("seq"))
    for case in cases(path):
        if case.get("red") and case.get("seq") in seqs:
            out[seqs.index(case["seq"])]["facts"]["won"] = "caught"
    return out


def line_pass(line, folder, roles, fm, root=None):
    """-> the pass one steps.jsonl line of the run folder `folder` stands
    for, its step's answer read from the file the line names."""
    step = line.get("step")
    said = ""
    kept = line.get("file")
    if kept and (folder / kept).is_file():
        said = (folder / kept).read_text(encoding="utf-8")
    return a_pass(step, roles.get(step, step), line.get("seconds") or 0,
                  line.get("handoff"),
                  _gates(line.get("gates"), gate_commands(fm, step, said),
                         gate_names(fm, step)),
                  line.get("ungated"), line.get("outcome") or "", said,
                  facts=facts_of(line, root), writes=writes_of(fm, step))


def cases(path):
    """-> the `case` of every line in steps.jsonl at `path`: what a test writer
    added for a reviewer's routed line, as held to the code."""
    out = []
    for raw in path.read_text(encoding="utf-8").split("\n"):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line.get("case"), dict):
            out.append(line["case"])
    return out


def _present(block):
    return block.get("state") in (handoff.PRESENT, handoff.PARTIAL)


def working(passes):
    """-> the last pass of a working role that handed over a block, else the
    last pass with one, else None."""
    for p in reversed(passes):
        if p["role"] not in JUDGING and _present(p["block"]):
            return p
    for p in reversed(passes):
        if _present(p["block"]):
            return p
    return None


def replay(passes):
    """-> (the step, the newest red-first result that replayed something),
    or (None, None) when no red-first gate did."""
    for p in reversed(passes):
        for g in p["gates"]:
            if g["gate"] == "red-first" and not g.get("skipped") and \
                    not g["detail"].startswith("not replayed"):
                return p["step"], g
    return None, None


def red_first(passes, held=True):
    """-> the red-first line. `held` False says the run's red-proof record
    holds no proof, so a red-test gate that went red proved nothing."""
    step, g = replay(passes)
    if g is not None:
        if not g["ok"]:
            return "the red-first gate failed on " + step + ": " + g["detail"]
        return "shown on " + step + ", " + g["detail"]
    for p in passes:
        for g in p["gates"]:
            if g["gate"] != "red-test" or g.get("skipped") or \
                    not g["detail"].startswith("red"):
                continue
            if not g["ok"]:
                return "the red-test gate failed on " + at(p) + ": " \
                    + g["detail"]
            if "nothing was run" in g["detail"]:
                return "claimed by " + at(p) + ", nothing was run"
            ran = (" (" + g["detail"]
                   + (", " + g["command"] if g["command"] else "") + ")")
            if not held:
                return ("not held: the red-test gate on " + at(p)
                        + " went red" + ran
                        + ", but the run holds no red proof")
            return "gate-proven on " + at(p) + ran
    return "not proven by a gate"


def shown(command, test, nt=os.name == "nt"):
    """the red-first gate's command with `test` for {test}, as a person runs
    it in their own shell: the results file the gate reads is the gate's,
    so its placeholder goes, with the flag before it when it stands alone,
    and the id is quoted the way cmd.exe (`nt`) or a POSIX shell reads."""
    words = command.split(" ")
    out = []
    for w in words:
        if "{results}" in w:
            if w == "{results}" and out and out[-1].startswith("-"):
                out.pop()
            continue
        out.append(w)
    quoted = subprocess.list2cmdline([test]) if nt else shlex.quote(test)
    return " ".join(quoted if w == "{test}" else w for w in out)


def by_hand(passes, proof, start=""):
    """-> the lines that say how to see the fix by hand, read from the run's
    red proof and the gates that ran its tests: each test the red-first
    replay showed red without the fix, with the exact command, or else the
    red-test gate's own command. [] when the run holds no red proof shown by
    a gate in it, or no gate kept a command that names its test."""
    if not proof or proof.get("how") != "gate":
        return []
    out = []
    step, g = replay(passes)
    red = [t["test"] for t in (g or {}).get("tests") or []
           if t.get("before") == "red"] if g and g["ok"] else []
    if red and "{test}" in g["command"]:
        out.append("- red without the fix and green with it, as the red-first"
                   " gate on " + step + " ran them:")
        out.extend("    " + shown(g["command"], t) for t in red)
    else:
        for p in passes:
            if p["step"] != proof.get("step"):
                continue
            for g in p["gates"]:
                if g["gate"] == "red-test" and g["ok"] and g["command"] \
                        and g["detail"].startswith("red") \
                        and "{test}" not in g["command"]:
                    out = ["- red before the fix, as the red-test gate on "
                           + at(p) + " ran it:", "    " + g["command"]]
                    break
            if out:
                break
    if out and start:
        files = sorted(proof.get("tests") or {})
        out.append("- without the fix: the run started at " + start[:7]
                   + "; the same command there, with " + ", ".join(files)
                   + (" as it is" if len(files) == 1 else " as they are")
                   + " now, fails")
    return out


def assumed(item):
    """an ASSUMED item -> one line with its labels: the choice, `why:` and
    `if wrong:`, read from the lines under the choice or, in the older
    one-line form, from between its `|` separators."""
    choice, why, cost = item, "", ""
    parts = [p.strip() for p in item.split("\n")]
    if len(parts) == 1:
        parts = [p.strip() for p in item.split("|")]
    if len(parts) > 1:
        choice = parts[0]
        for p in parts[1:]:
            low = p.lower()
            if low.startswith("why:"):
                why = p[4:].strip()
            elif low.startswith("if wrong:"):
                cost = p[9:].strip()
            else:
                choice = choice + " | " + p
    out = choice.rstrip("?.") + "?"
    if why:
        out = out + " why: " + why + "."
    if cost:
        out = out + " if wrong: " + cost + "."
    return out


YES = ("yes", "y", "true", "fixed")
NO = ("no", "n", "false", "not fixed", "not yet")


def beside(item):
    """an ADJACENT item -> {"defect", "fixed", "test"}: `fixed` True, False
    or None when the step did not say, `test` "" when it named none. read
    from the lines under the defect or, in a one-line form, from between its
    `|` separators."""
    parts = [p.strip() for p in item.split("\n")]
    if len(parts) == 1:
        parts = [p.strip() for p in item.split("|")]
    out = {"defect": parts[0], "fixed": None, "test": ""}
    for p in parts[1:]:
        low = p.lower()
        if low.startswith("fixed:"):
            said = p[6:].strip().lower().rstrip(".")
            out["fixed"] = True if said in YES else False if said in NO \
                else None
        elif low.startswith("test:"):
            said = p[5:].strip().strip("`")
            out["test"] = "" if said.lower() in handoff.NONE_WORDS else said
        else:
            out["defect"] = out["defect"] + " | " + p
    return out


def beside_said(found, files=None):
    """-> how a found defect stands: fixed and by which test, or not. a
    test named for a fix whose file is not among `files`, the paths the run
    changed (None outside git), says so."""
    if found["fixed"] is None:
        return "fixed or not, not said"
    if not found["fixed"]:
        return "not fixed"
    if not found["test"]:
        return "fixed, no test names it"
    out = "fixed, shown by " + found["test"]
    path = found["test"].split("::")[0].replace("\\", "/")
    if files is not None and path not in files:
        out = out + "; its file did not change in this run"
    return out


def found_beside(blocks):
    """-> each defect the steps found beside the change, once: [(found, the
    roles that named it)], as the last step that named it left it."""
    out = []
    for role, b in blocks:
        if not _present(b):
            continue
        for item in b.get("adjacent") or []:
            found = beside(item)
            key = front.norm(found["defect"])
            home = next((h for h in out if front.norm(h[0]["defect"]) == key),
                        None)
            if home is None:
                out.append((found, [role]))
                continue
            home[0].update(fixed=found["fixed"], test=found["test"])
            if role not in home[1]:
                home[1].append(role)
    return out


WRITING = ("tests", "product", "spec")
NOTHING = ("nothing", "none", "no change", "nothing changed")
LED = re.compile(r"^(TRIED|ASSUMED|QUESTION|DECIDED)\b\W*(.*)$", re.I)
SPOT = re.compile(r"^(\S+?):(\d+)(?:\s*-\s*(\d+))?$")
SPAN = re.compile(r"(\d+)(?:-(\d+))?")
UNHELD = "(not in the record)"
UNBACKED = "why_unbacked"


def writes_of(fm, step):
    """-> what the flow says `step` writes (`tests`, `product`, `spec`,
    `none`), "" when it does not say."""
    for s in getattr(fm, "steps", None) or []:
        if step_id(s) == step:
            return s.get("writes") or ""
    return ""


def _path(text):
    text = text.strip().strip("`'\"<>").replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def _tail(a, b):
    """whether two paths or test ids name the same thing, one perhaps by its
    tail: `test_calc.py::t` is `tests/test_calc.py::t`, `t` is either."""
    a, b = _path(a).lower(), _path(b).lower()
    if not a or not b:
        return False
    return a == b or a.endswith("/" + b) or b.endswith("/" + a) \
        or a.endswith("::" + b) or b.endswith("::" + a)


def _spans(text):
    """-> [(first, last)] for a `git diff` range line, "2, 5-7"; a range
    where lines were only taken out is the line it was taken out after."""
    return [(int(a), int(b or a)) for a, b in SPAN.findall(text or "")]


def record_of(passes, changes, decided, proof):
    """-> what a reason's `led to:` is held to: the test ids the red proof and
    the gates hold, the test files the red proof holds with no id listed, the
    files the run changed with the lines each change covers and the names it
    touches in each, and the rulings on record."""
    ids, commands = [], []
    for p in passes:
        for g in p["gates"]:
            ids.extend(t["test"] for t in g.get("tests") or []
                       if isinstance(t, dict) and t.get("test"))
            if g.get("command"):
                commands.append(g["command"])
    proved = []
    if proof:
        listed = [i for i in proof.get("ids") or [] if isinstance(i, str)]
        ids.extend(listed)
        proved = [f for f in proof.get("tests") or {}
                  if not any(_tail(i.split("::")[0], f) for i in listed)]
    files, names = {}, {}
    if changes.get("git"):
        spans = changes.get("ranges") or {}
        for path, _, _, how in changes.get("files") or []:
            files.setdefault(path, []).extend(
                _spans(spans.get((path, how.split(",")[0]), "")))
        names = dict((p, set(n)) for p, n in
                     (changes.get("names") or {}).items())
    return {"ids": ids, "proved": proved, "commands": commands,
            "files": files, "names": names, "decided": list(decided)}


CODE = re.compile(r"`([^`]+)`")


def _which(said, items):
    """-> the index of the one of `items` that `said` names, by its words, or
    by the names it quotes in backticks when every one is in the item: bare,
    it names the first there is; None for none. an item read inside `said`,
    or the names it quotes, count only when they say enough to name one."""
    want = handoff.norm(said).strip(" .:;<>")
    if not want:
        return 0 if items else None
    quoted = CODE.findall(said)
    for n, i in enumerate(items):
        head = handoff.norm(i.split("\n")[0]).split(" - ")[0].strip()
        if want in handoff.norm(i) or (_names_one(head) and head in want):
            return n
        if _names_one(" ".join(quoted)) and all(q in i for q in quoted):
            return n
    return None


def _among(said, items):
    return _which(said, items) is not None


def _names_one(text):
    """whether `text` says enough to name one item: three words or twelve
    letters. a bare label names none, however many items there are."""
    words = handoff.norm(text).strip(" .:;<>")
    return len(words.split()) >= 3 or len(words) >= 12


OWN = re.compile(r"\b(WOULD PASS|CATCH)\b")
NOTE = re.compile(r"\s+\(|\s*[;,]\s+")
LINES = re.compile(r"^(?:(?:new|changed|added)\s+)?lines?\s+(\d+)"
                   r"(?:\s*-\s*(\d+))?$", re.I)
CALLED = re.compile(r"^`([A-Za-z_][\w.]*)(?:\(\))?`$"
                    r"|^([A-Za-z_]*_[\w.]*|[A-Za-z_][\w.]*\(\))$")


def led(said, block, record, step=None):
    """whether the record holds what one `led to:` names (`held_at`)."""
    return bool(held_at(said, block, record, step))


# what `held_at` says of a `led to:` that led to nothing
LED_NOWHERE = "nothing"


def held_at(said, block, record, step=None):
    """-> where the record holds what one `led to:` names, "" when it does
    not: `nothing` always (LED_NOWHERE); a TRIED or ASSUMED item among the
    block's own, by its words; a QUESTION the block asks, bare or by its
    words; a DECIDED one among the rulings on record or the step's own
    DECIDED lines, by its words, or the one such line the step gave; the
    step's own WOULD PASS and CATCH lines, by name; a `<file>:<lines>` in
    the diff, its lines among the lines the change covers; a test id the red
    proof or a gate holds, or one in a test file the red proof holds with no
    id listed. a line that leads with a file or a test id and goes on with a
    note is held to what it leads with: a function the change touches in
    that file, its lines, each further file or test id it lists."""
    said = _unquoted(said or "")
    step = step or {}
    if not said:
        return ""
    if said.lower().rstrip(".") in NOTHING:
        return LED_NOWHERE
    m = LED.match(said)
    if m:
        kind, rest = m.group(1).upper(), m.group(2)
        if kind != "QUESTION" and not _names_one(rest):
            return ""
        if kind in ("TRIED", "ASSUMED"):
            n = _which(rest, block.get(kind.lower()) or [])
            return "" if n is None else (kind + " item " + str(n + 1)
                                         + " of its handoff")
        if kind == "QUESTION":
            return "a QUESTION of its handoff" if _among(
                rest, [q["question"] for q in block.get("questions") or []]
                + (block.get("other") or {}).get("NEEDS", [])) else ""
        own = []
        for d in [step.get("ruled")] + (block.get("other") or {}).get(
                "DECIDED", []):
            if d and handoff.norm(d) not in [handoff.norm(o) for o in own]:
                own.append(d)
        if len(own) == 1:
            return "its DECIDED line"
        n = _which(rest, [d.decided + " - " + d.why for d in record["decided"]]
                   + own)
        if n is None:
            return ""
        if n < len(record["decided"]):
            return "decisions.md " + stamp(record["decided"][n])
        return "its DECIDED line"
    named = OWN.findall(said)
    if named:
        would = step.get("would")
        if not would or ("CATCH" in named and not would[1]):
            return ""
        return "its " + " and ".join(sorted(set(named), reverse=True)) \
            + " lines"
    held = _held(said, record)
    if held:
        return held
    pieces = []
    for p in NOTE.split(said):
        p = p.rstrip(")") if p.count(")") > p.count("(") else p
        if _unquoted(p):
            pieces.append(_unquoted(p))
    if not pieces:
        return ""
    if pieces[0].lower().rstrip(".") in NOTHING:
        return LED_NOWHERE
    if not _shaped(pieces[0]):
        return ""
    out = []
    for p in pieces:
        if not _shaped(p):
            continue
        held = _noted(p, record)
        if not held:
            return ""
        if held not in out:
            out.append(held)
    return "; ".join(out)


def _unquoted(text):
    """-> `text` stripped, and the backticks round it taken off when no other
    is inside."""
    text = text.strip()
    inner = text.strip("`")
    return text if "`" in inner else inner.strip()


def _shaped(piece):
    """whether a piece of a `led to:` leads with a file or a test id rather
    than prose."""
    word = _path(piece.split()[0])
    return "::" in word or "/" in word or bool(SPOT.match(word)) \
        or bool(re.search(r"\w\.\w+$", word))


def _noted(piece, record):
    """-> where the record holds a file or a test id with what follows it:
    its lines (`new lines 4-6`), a function quoted after it, or a note; ""
    when it does not."""
    head, _, rest = piece.partition(" ")
    rest = rest.strip()
    if not rest:
        return _held(head, record)
    lines = LINES.match(rest)
    if lines:
        return _held(head + ":" + lines.group(1)
                     + ("-" + lines.group(2) if lines.group(2) else ""),
                     record)
    called = CALLED.match(rest)
    if not called:
        return "" if rest.startswith("`") else _held(head, record)
    name = (called.group(1) or called.group(2)).rstrip("()").split(".")
    for have, names in record.get("names", {}).items():
        if _tail(head, have) and all(n in names for n in name):
            return ("the diff of " + have + ", in `" + ".".join(name)
                    + "`")
    return ""


def _span(a, b):
    return str(a) if a == b else str(a) + "-" + str(b)


def _held(said, record):
    """-> where the record holds one file, `<file>:<lines>` or test id, ""
    when it does not."""
    if "::" not in said:
        spot = SPOT.match(said)
        path = spot.group(1) if spot else said
        for have, spans in record["files"].items():
            if not _tail(path, have):
                continue
            if not spot or not spans:
                return "the diff of " + have
            first = int(spot.group(2))
            last = int(spot.group(3) or first)
            hit = [(a, b) for a, b in spans if a <= last and first <= b]
            if hit:
                return ("the diff of " + have + ", lines "
                        + ", ".join(_span(a, b) for a, b in hit))
    for i in record["ids"]:
        if _tail(said, i):
            return "test " + i
    if "::" in said:
        for f in record.get("proved", ()):
            if _tail(said.split("::")[0], f):
                return "the red proof's test file " + f
        for c in record["commands"]:
            if said in c:
                return "a gate's command: " + c
    return ""


def reasons(passes, record):
    """-> [(role, [line]), ...] for every role that gave a reason and every
    step that writes a file, the role's reasons once each in the order given:
    `because <reason> (<from>) -> <what it led to>`, or `-> (not in the
    record)`. a writing step that gave none says `none given`; one that
    handed over no block is under not verified as missing already. and the
    count the record does not hold."""
    out, unheld = [], []
    for p in passes:
        b = p["block"]
        if not _present(b):
            continue
        mine = next((r for r in out if r[0] == p["role"]), None)
        if mine is None:
            mine = (p["role"], [])
            out.append(mine)
        for item in b.get("because") or []:
            r = handoff.reason(item)
            held = led(r["led_to"], b, record, p)
            line = ("because " + r["reason"] + " (" + (r["from"] or "own read")
                    + ") -> " + (r["led_to"] if held else UNHELD))
            if line not in mine[1]:
                mine[1].append(line)
                if not held:
                    unheld.append((p["role"], r))
    writing = set(p["role"] for p in passes if p.get("writes") in WRITING)
    out = [(role, lines or ["none given"]) for role, lines in out
           if lines or role in writing]
    return out, unheld


def evidence(p, record):
    """-> where the record holds what each reason `p` gave led to, once each,
    for every reason that led to something the record holds: the runner's
    words for it, never the reason's own."""
    out = []
    b = p["block"]
    if not _present(b):
        return out
    for item in b.get("because") or []:
        cite = held_at(handoff.reason(item)["led_to"], b, record, p)
        if cite and cite != LED_NOWHERE and cite not in out:
            out.append(cite)
    return out


# the label of a role's reasons in the why section, after the role
REASONS_OF = "'s reasons, and what each led to:"
UNSHOWN = "- reasons the record does not show: "


def without_reasons(text):
    """-> handoff.md's text with the steps' own reasons taken out: the why
    section's reasons under each role, the reasons section, and the reasons
    not verified lists. what is left is the record as it was."""
    out = []
    section = labelled = False
    for line in text.split("\n"):
        if line.startswith("## "):
            section, labelled = line == "## reasons", False
        if section:
            continue
        if line.endswith(REASONS_OF):
            labelled = True
            continue
        if labelled and line.startswith("- "):
            continue
        labelled = False
        if not line.startswith(UNSHOWN):
            out.append(line)
    return "\n".join(out)


def ended(stopped, unsure=()):
    """-> the words after the run id: the outcome first, then for a stop
    where and why."""
    out = outcome(stopped, unsure)
    if not stopped:
        return out
    why = stopped.get("why") or ""
    out = out + " at " + stopped["at"]
    return out + (" - " + stops.flat(why) if why else "")


def left_undone(stopped, needs, changes):
    """-> the plain line a stopped run's "not done" leads with: where it
    stopped, the steps its needs section says are left to run, and what
    git says of what it changed. None on a run that did not stop."""
    if not stopped:
        return None
    from agentweft.orchestrate import park

    at = stopped["at"]
    if stopped["cause"] == stops.DECLINED:
        return ("not done: the work the task asked for; " + at
                + " declined it, and the run ends on that")
    left = park.left_of(needs)
    out = "not done: the run stopped at " + at
    if left:
        out = out + "; left to run: " + ", ".join(left)
    elif left == []:
        return (out + " with no step left to run after it; what carries it"
                " on is under needs you")
    else:
        out = out + "; the steps after it have not run"
    if not changes.get("git"):
        return out
    files = changes.get("files") or []
    if not files:
        return out + "; nothing in the tree changed"
    return (out + "; the " + (str(len(files)) + " files" if len(files) > 1
                              else "file") + " it changed "
            + ("are" if len(files) > 1 else "is") + " not taken as done")


def asks(passes):
    """-> the lines a step wrote that only a person can answer: a NEEDS or
    REFUSED line with its cites and options, read by the verb parser."""
    out = []
    for p in passes:
        v = p["verbs"]
        if v.needs:
            out.append("- " + p["role"] + " asks: " + v.needs)
        if v.refused:
            out.append("- " + p["role"] + " refused: " + v.refused)
        if v.needs or v.refused:
            out.extend("  cites: " + c for c in v.cites)
            out.extend("  option: " + o for o in v.options)
    return out


def _grouped(found):
    """[(path, range)] -> "a.py:1-2, 9-12; b.py (whole file)", in the order
    first read."""
    order, spans = [], {}
    for path, span in found:
        if path not in spans:
            order.append(path)
            spans[path] = []
        if span not in spans[path]:
            spans[path].append(span)
    return "; ".join(path + " (whole file)" if "" in spans[path]
                     else path + ":" + ", ".join(spans[path])
                     for path in order)


ITEM_PATH = re.compile(r"^[`\"']?([^\s:`\"']+)")


def _named(item, paths):
    """whether a READ line a step wrote names one of the files read."""
    m = ITEM_PATH.match(item.strip())
    if not m:
        return False
    said = m.group(1).replace("\\", "/")
    return any(said == p or p.endswith("/" + said) or said.endswith("/" + p)
               for p in paths)


def read_lines(passes):
    """the files and ranges each pass read, from its transcript, and the
    READ lines the step wrote beside them; a READ line its transcript does not
    show is marked so."""
    out = []
    for p in passes:
        found = p.get("facts", {}).get("read")
        said = p["block"]["read"] if _present(p["block"]) else []
        if found is None and not said:
            continue
        if found is None:
            out.append("- " + at(p) + ": no transcript to read it from")
        elif found:
            out.append("- " + at(p) + " read: " + _grouped(found))
        else:
            out.append("- " + at(p) + " read no file, by its transcript")
        paths = [path for path, _ in found or []]
        for item in said:
            shown = found is None or _named(item, paths)
            out.append(("  said: " if shown else
                        "  said, not in its transcript: ") + item)
    return out or ["- no pass has a transcript or a READ line"]


SPEC_REF = re.compile(r"[\w./-]+\.md:\d+(?:-\d+)?")


def spec_for(test, blocks):
    """-> " - encodes <spec line> (<role>)" from the first line a step wrote
    naming the test and a spec line, "" when none did."""
    name = (test or "").split("::")[-1]
    if not name:
        return ""
    for role, b in blocks:
        if not _present(b):
            continue
        items = [i for key in ("did", "must_not_miss", "assumed", "doubts")
                 for i in b[key]] + [i["claim"] for i in b["verified"]]
        for item in items:
            ref = SPEC_REF.search(item)
            if name in item and ref:
                return " - encodes " + ref.group(0) + " (" + role + ")"
    return ""


def _money(facts):
    if facts.get("cached"):
        return "cached"
    cost = facts.get("cost")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return "cost not stated"
    out = "$%.4f" % cost
    came = facts.get("cost_from") or {}
    if came:
        out = out + ", " + ", ".join(k + " x" + str(n)
                                     for k, n in sorted(came.items()))
    return out


def retro(passes):
    """one line per pass: its seconds and cost, its outcome when not ok, the
    gates it failed, what each gate could not do, its retries, the limit and
    refusals it met, the shell trouble it recovered from; then one line per
    send-back with why."""
    out = []
    for p in passes:
        f = p.get("facts") or {}
        said = []
        if p["outcome"] == "redo":
            said.append("sent back")
        elif p["outcome"] not in ("ok", ""):
            said.append(p["outcome"])
        said.extend("failed " + g["gate"] + (" - " + stops.flat(g["detail"])
                                             if g["detail"] else "")
                    for g in p["gates"] if not g["ok"])
        said.extend("issue: " + stops.flat(g["issue"]) for g in p["gates"]
                    if g.get("issue"))
        for cause, n in sorted((f.get("retries") or {}).items()):
            if not n:
                continue
            if cause == "outage":
                said.append("limit events " + str(n))
            elif cause == "fatal":
                said.append("refused calls " + str(n))
            else:
                said.append("retried after " + cause + " " + str(n))
        for key, words in (("shell_writes_denied", "shell writes refused"),
                           ("shell_trap_recoveries", "shell-trap recoveries"),
                           ("background_killed", "leftover processes ended")):
            if f.get(key):
                said.append(words + " " + str(f[key]))
        took = p["seconds"] if p["seconds"] is not None else 0
        out.append("- " + at(p) + " " + str(took) + "s (" + _money(f) + ")"
                   + won_words(p) + ": " + ("; ".join(said) or "no events"))
    out.extend("- " + p["step"] + " sent the work back: " + p["redo_why"]
               for p in passes if p["outcome"] == "redo" and p["redo_why"])
    if not out:
        return ["- no step ran"]
    return out + bought(passes)


def _tally(passes):
    seconds = round(sum(p["seconds"] or 0 for p in passes), 1)
    costs = [(p.get("facts") or {}).get("cost") for p in passes]
    stated = [c for c in costs if isinstance(c, (int, float))
              and not isinstance(c, bool)]
    out = (str(len(passes)) + (" pass" if len(passes) == 1 else " passes")
           + ", " + str(seconds) + "s, $%.4f" % sum(stated))
    if len(stated) < len(costs):
        out = out + ", cost not stated on " + str(len(costs) - len(stated))
    return out


def won_words(p):
    """-> what a pass won, in words: `won` as the line keeps it, one of
    `trace.WON`; the retro's own product, the facts it wrote, the docs it
    had edited, the guards written and the items refused, in place of a
    `none` that would read as nothing bought; and the checks a pass that
    won nothing still made."""
    f = p.get("facts") or {}
    if not f.get("won"):
        return ""
    kept = f.get("kept_facts")
    if p["step"] == retro_step() and kept is not None:
        kinds = [a.get("kind") for a in kept.get("applied") or []
                 if isinstance(a, dict)]
        return (", won facts " + str(len(kept.get("written") or []))
                + ", docs " + str(sum(1 for k in kinds if k != "guard"))
                + ", guards " + str(kinds.count("guard"))
                + " (" + str(len(kept.get("refused") or [])) + " refused)")
    if f["won"] == "none" and f.get("checked") is not None:
        return ", won none, checked " + str(f["checked"])
    return ", won " + f["won"]


def retro_step():
    from .retro import STEP

    return STEP


def _cost(p):
    c = (p.get("facts") or {}).get("cost")
    return c if isinstance(c, (int, float)) and not isinstance(c, bool) else 0


def _unstated(passes):
    """-> ", cost not stated on n" for the passes whose cost is not known,
    so a sum of the rest never reads as their price."""
    n = sum(1 for p in passes if not isinstance(
        (p.get("facts") or {}).get("cost"), (int, float))
        or isinstance(p["facts"]["cost"], bool))
    return ", cost not stated on " + str(n) if n else ""


def bought(passes):
    """the spend and seconds of every pass summed by what it won, `none`
    always among them; what the gates and police refused; the spend on
    passes that won nothing, split by whether they checked anything, with
    the retro's upkeep beside it and never in it; then the total, which is
    the sum of the steps."""
    groups = {}
    for p in passes:
        groups.setdefault((p.get("facts") or {}).get("won") or "not recorded",
                          []).append(p)
    groups.setdefault("none", [])
    order = list(trace.WON) + ["not recorded"]
    out = ["- won " + k + ": " + _tally(groups[k]) for k in order
           if k in groups]
    refused = {}
    for p in passes:
        for gate in (p.get("facts") or {}).get("prevented") or ():
            refused[gate] = refused.get(gate, 0) + 1
    if refused:
        out.append("- prevented: " + str(sum(refused.values())) + " refusal"
                   + ("" if sum(refused.values()) == 1 else "s") + " ("
                   + ", ".join(g + ": " + str(n)
                               for g, n in sorted(refused.items())) + ")")
    upkeep = [p for p in passes if p["step"] == retro_step()]
    idle = [p for p in passes if p not in upkeep
            and (p.get("facts") or {}).get("won") == "none"
            and (p.get("facts") or {}).get("checked") is not None]
    waste = [p for p in idle if not p["facts"]["checked"]]
    price = [p for p in idle if p["facts"]["checked"]]
    out.append("- USD on steps that won nothing and checked nothing: $%.4f of"
               " $%.4f" % (sum(_cost(p) for p in waste),
                          sum(_cost(p) for p in passes)) + _unstated(waste))
    out.append("- USD on steps that won nothing and checked "
               + str(sum(p["facts"]["checked"] for p in price))
               + ": $%.4f" % sum(_cost(p) for p in price) + _unstated(price))
    if upkeep:
        out.append("- upkeep, not waste: the retro $%.4f"
                   % sum(_cost(p) for p in upkeep))
    return out + thought(passes) + ["- total: " + _tally(passes)]


def thought(passes):
    """-> the thinking tokens summed by role, each with the effort its
    transcripts ran at, and the passes whose provider did not say; nothing
    when no pass said."""
    by, at, unsaid = {}, {}, 0
    for p in passes:
        f = p.get("facts") or {}
        n = f.get("thinking")
        if not isinstance(n, int) or isinstance(n, bool):
            unsaid += 1
            continue
        role = p.get("role") or p["step"]
        by[role] = by.get(role, 0) + n
        used = (f.get("effort") or {}).get("used") \
            if isinstance(f.get("effort"), dict) else None
        if used:
            at.setdefault(role, set()).add(used)
    if not by:
        return []
    said = [role + " " + str(n) + (" at " + ", ".join(sorted(at[role]))
                                   if role in at else "")
            for role, n in by.items()]
    if unsaid:
        said.append("not said on " + str(unsaid) + " pass"
                    + ("" if unsaid == 1 else "es"))
    return ["- thinking tokens by role: " + ", ".join(said)]


AFTER = " (after this handoff was written)"


def section(lines, heading):
    """-> (first, end) of `## heading`'s lines below its heading, end the
    index past the last; None when the handoff has no such section."""
    if "## " + heading not in lines:
        return None
    first = lines.index("## " + heading) + 1
    end = next((n for n in range(first, len(lines))
                if lines[n].startswith("## ")), len(lines))
    while end > first and not lines[end - 1].strip():
        end -= 1
    return first, end


def after_retro(path, every, spend, police=None):
    """the handoff the retro read, once the retro has run: the retro's pass
    in the retro section with the sums taken again over every pass, and the
    run's spend as it stands. `every` is every pass, the retro's last.
    `police` is the police section with what police saw of the retro, None
    when police did not read it."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    found = section(lines, "retro")
    if found:
        first, end = found
        sums = [n for n in range(first, end) if lines[n].startswith("- won ")
                or lines[n].startswith("- total: ")]
        if sums:
            lines[sums[0]:sums[-1] + 1] = ([retro(every[-1:])[0] + AFTER]
                                           + bought(every))
    found = section(lines, "run")
    if found:
        top = found[0]
        while top < found[1] and trace.SWITCHED in lines[top]:
            top += 1
        lines[top:top] = fallen(every[-1:])
        for n in range(*section(lines, "run")):
            if lines[n].startswith("- spend: "):
                lines[n] = "- spend: " + spend + ", the retro's call included"
                break
    found = section(lines, "police")
    if found and police:
        lines[found[0]:found[1]] = police
    elif police and not found and "## carry forward" in lines:
        at = lines.index("## carry forward")
        lines[at:at] = ["## police"] + police + [""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def wall(passes, clock):
    """-> the line that puts this run's wall beside the seconds of its
    steps and its gates, and the runner's own, which is the rest: the three
    add up to the wall, unless fanned tasks ran at once."""
    steps = round(sum(p["seconds"] or 0 for p in passes), 1)
    gates = round(clock["gates"], 1)
    whole = round(clock["wall"], 1)
    # 0.3 - 0.1 - 0.2 rounds to -0.0, which prints as "-0.0"
    rest = round(whole - steps - gates, 1) + 0.0
    if rest < 0:
        return ("- wall " + str(whole) + "s: steps " + str(steps)
                + "s summed, past the wall because fanned tasks ran side by"
                " side, gates " + str(gates) + "s")
    return ("- wall " + str(whole) + "s: steps " + str(steps) + "s, gates "
            + str(gates) + "s, runner " + str(rest) + "s")


def changed_lines(changes):
    """the changed section: each file with its line counts, how it stands
    and the lines it covers, then what git status and git log print."""
    if not changes.get("git"):
        return ["- not a git checkout, so what changed is not recorded"]
    out = []
    spans = changes.get("ranges") or {}
    for path, a, d, how in changes["files"]:
        span = spans.get((path, how.split(",")[0]))
        out.append("- " + path + " +" + str(a) + " -" + str(d) + " (" + how
                   + ")" + (", lines " + span if span else ""))
    if not changes["files"]:
        out.append("- nothing changed in the tree")
    status = changes.get("status") or []
    out.append("- git status --short:" + ("" if status else " prints nothing"))
    out.extend("    " + l for l in status)
    start = changes.get("start")
    if not start:
        out.append("- git log: no commit to start from")
        return out
    log = changes.get("log") or []
    out.append("- git log --oneline " + start[:7] + "..HEAD:"
               + ("" if log else " prints nothing"))
    out.extend("    " + l for l in log)
    return out


def build(run_id, flow_name, task, passes, changes, decided, spend,
          stopped=None, needs=None, command=None, before=(), started=None,
          found="", order="", left=None, suite=(), chained=None,
          skipped=(), kept="", worktree=(), headline="", signed=(),
          spec_files=None, clock=None, held=True, proof=None, shadowed=(),
          told=(), police=(), sized=(), unwired=()):
    """-> the lines of handoff.md.

    `passes` is this run's passes in order and `before` the ones of the run
    it picked up, if any; `changes` is `Tree.changes()`; `decided` is every
    decisions.md entry in the place; `stopped` is {"cause", "why", "at"} for
    a run that stopped short, with the "question" it waits on when it asked
    one; `needs` is the park section's lines when the
    run waits for someone; `command` is the line that carries on; `found` is
    the investigator's answer when the flow ran one; `order` is the line on
    the red test the run holds before product code, "" for none; `left` is
    what a stop found of the tests the run added or changed (`leftred.check`);
    `suite` is the lines on the suite as the run found it (`baseline.lines`);
    `chained` is the head of steps.jsonl it was written from (`chain.head`).
    `skipped` is a line per reason the run skipped gates or cut steps by
    name for.
    `kept` is the line on the run's own commits, "" when it makes none.
    `worktree` is the section on the run's own worktree and `headline` its
    line at the top, both empty for a run in the tree it was started from.
    `signed` is what the sign-off said of the change (`signoff.Signed`).
    `spec_files` is the flow's rule for the spec files.
    `clock` is {"wall", "gates"}, the seconds of this run and of its gates,
    None for no wall line.
    `held` is False when the flow orders tests before product code and the
    run's red-proof record holds no proof (`redorder.Order`).
    `proof` is the run's red proof (`redorder.Order.proof`), None for none.
    `shadowed` is every tripwire hit of a run with `police: shadow`, a line
    each, and `police` that run's police section (`police.handoff_lines`),
    empty in any other mode. `told` is a line per passage addressed to an
    agent that a step read and took no action from (`police.read_lines`),
    empty with police off.
    `sized` is a line on the size of the change and one per reviewer it left
    out, empty for a flow with no `small_reviewers`. `unwired` is a line per
    def or class the run added that nothing in the product calls
    (`gating.unwired_lines`), printed under "changed".
    """
    every = list(before) + list(passes)
    blocks = [(p["role"], p["block"]) for p in every]
    last = working(every)
    dug = investigate.sections(found)
    first_line = (task or "").strip().split("\n")[0] if task else ""
    unsure = unproven(every)
    out = ["# " + flow_name + " " + run_id + ": " + ended(stopped, unsure)]
    if last and last["block"]["did"] and not stopped:
        out[0] = out[0] + " - " + last["block"]["did"][0]
    out.append("")

    ran = " -> ".join(p["step"] + (" (sent back)" if p["outcome"] == "redo"
                                    else "") for p in passes)
    secs = round(sum(p["seconds"] or 0 for p in passes), 1)
    line = flow_name + " ran " + (ran or "nothing") + " in " + str(secs) + "s"
    if before:
        line = (flow_name + " picked up " + str(len(before)) + " earlier pass"
                + ("" if len(before) == 1 else "es") + " and ran "
                + (ran or "nothing") + " in " + str(secs) + "s")
    line = line + (" on: " + first_line if first_line else "")
    out.append(line + ("" if line.endswith((".", "!", "?")) else "."))
    if dug.get("CAUSE"):
        out.append(cause(dug["CAUSE"][0]))
    gates = [g for p in every for g in p["gates"]]
    unrun = sum(1 for g in gates if g.get("skipped"))
    passed = sum(1 for g in gates if g["ok"] and not g.get("skipped"))
    checks = (str(passed) + " of " + str(len(gates)) + " gates passed"
              + (", " + str(unrun) + " skipped" if unrun else "")
              if gates else "")
    made = (stopped or {}).get("checked") or []
    checks = "; ".join([c for c in [checks] if c] + [
        "1 check " + ("passed" if ok else "failed") + " (" + found + ")"
        for _, ok, found in made]) or "no gates ran"
    now = leftred.red_now(left) if stopped else ""
    out.append("suite: " + checks + ("; " + now if now else "")
               + "; red first: " + red_first(every, held)
               + ("; " + order if order.startswith("tests skipped") else "")
               + "".join("; " + s for s in skipped) + ".")
    if changes.get("git"):
        files = changes["files"]
        out.append("changed: " + (str(len(files)) + " file"
                                  + ("" if len(files) == 1 else "s")
                                  if files else "nothing in the tree")
                   + ", " + str(len(changes["commits"])) + " commit"
                   + ("" if len(changes["commits"]) == 1 else "s")
                   + " (from git, below)"
                   + ("; " + leftred.count(left) if leftred.count(left)
                      else "") + ".")
    else:
        out.append("changed: not a git checkout, so what changed is not"
                   " recorded here.")
    if headline:
        out.append(headline)

    still = still_open(every, stopped)
    owed = rulings(changes, decided, spec_files)
    extra = [front.point(investigate.STEP, l[2:]) for l in
             investigate.listed(dug, "DECISIONS")]
    extra.extend(front.point("runner", "rule on " + l[2:]) for l in owed
                 if "UNRULED" in l)
    waits = front.stopped_on(stopped, still, every)
    points, taken = front.questions(every, extra,
                                    asking=[] if waits else still,
                                    settled=settled(decided, every, run_id))
    found = front.clusters(([waits] if waits else []) + points)
    if last and stopped:
        why = [(last["role"] + " handed over this before the stop, not taken"
                " as done:", did_of(every, last["role"]))]
    elif last:
        why = [(last["role"] + " did:", did_of(every, last["role"]))]
    else:
        why = [(None, ["no step handed over a block, so what was done is"
                       " only what git and the gates show in the full"
                       " record."])]
    gave, unheld = reasons(every, record_of(every, changes, decided, proof))
    why.extend((role + REASONS_OF, lines) for role, lines in gave)
    dropped = []
    for line in ([role + ": " + i for role, b in blocks if _present(b)
                  for i in b["tried"]]
                 + [investigate.STEP + " ruled out: " + l[2:]
                    for l in investigate.listed(dug, "RULED OUT")]):
        if line not in dropped:
            dropped.append(line)
    why.append(("tried and dropped, and why:", dropped))
    why.append(("assumed - tell me if wrong:",
                [role + ": " + assumed(i) for role, b in blocks
                 if _present(b) for i in b["assumed"]]))
    files = [f[0].replace("\\", "/") for f in changes.get("files") or []] \
        if changes.get("git") else None
    beside_it = found_beside(blocks)
    why.append(("also fixed beside the change:",
                [f["defect"] + (", shown by " + f["test"] if f["test"]
                                else ", no test names it")
                 + " (" + ", ".join(roles) + ")"
                 for f, roles in beside_it if f["fixed"]]))
    left_out = []
    for role, b in blocks:
        if _present(b):
            for i in b["not_verified"]:
                line = role + ": " + i
                if all(front.norm(i) != front.norm(l.split(": ", 1)[1])
                       for l in left_out):
                    left_out.append(line)
    plain = left_undone(stopped, needs, changes)
    not_done = [(None, [plain] if plain else []),
                ("not verified:", left_out + [step + " unproven: " + line
                                              for step, line in unsure]),
                ("doubts, left as they are:",
                 [text + " (" + who + ")" for text, who in
                  front.doubts(every, taken)]
                 + [investigate.STEP + " saw and did not fix: " + l[2:]
                    for l in investigate.listed(dug, "RELATED")]),
                ("found beside the change, not fixed:",
                 [f["defect"] + ("" if f["fixed"] is False
                                 else ", fixed or not, not said")
                  + " (" + ", ".join(roles) + ")"
                  for f, roles in beside_it if not f["fixed"]]),
                ("a fact's check broken at the end of the run:",
                 check_left(every)),
                ("cut for the budget, not run:", cut_lines(skipped)),
                ("police, shadow - seen, the run not stopped for it:",
                 list(shadowed)),
                ("read, addressed to an agent, not acted on:", list(told))]
    stop = None
    if stopped and not (found and found[0]["kind"] in front.WAITS):
        carry = carry_on(needs, command)
        stop = (ended(stopped), front.DECLINED
                if stopped["cause"] == stops.DECLINED else front.CARRY,
                front.advice(stopped, carry[1].strip()
                             if carry[0] == CARRY_ON else ""))
    view = front.view(out, found, why, not_done,
                      front.gaps(found, changes.get("spec_changed", []),
                                 lead=not stop), stop=stop)
    out[:] = view
    out.append("")
    out.extend(front.pointer(run_id))

    asked = asks(still)
    asked.extend("- " + investigate.STEP + " leaves to you: " + l[2:]
                 for l in investigate.listed(dug, "DECISIONS"))
    if stopped or asked:
        out.append("")
        out.append("## needs you")
        out.extend(asked)
        red = leftred.lines(left) if stopped else []
        if red:
            if asked:
                out.append("")
            out.extend(red)
        if (asked or red) and stopped:
            out.append("")
        if needs:
            out.extend(needs)
        elif stopped:
            out.append(ended(stopped) + ".")
            out.append("what " + stopped["at"] + " answered is in runs/"
                       + run_id + "/" + stopped["at"] + ".")
            if command:
                out.append("")
                out.append("to run again from there")
                out.append("  " + command)
    out.extend(worktree)

    out.append("")
    out.append("## assumed - tell me if wrong")
    said = ["- " + role + ": " + assumed(i) for role, b in blocks
            if _present(b) for i in b["assumed"]]
    out.extend(said or ["- nothing assumed, or no step said"])

    asked_too = front.unprinted(found, front.shown(found, view))
    if asked_too:
        out.append("")
        out.append("## open questions")
        out.extend(asked_too)

    out.append("")
    out.append("## doubts")
    said = ["- " + who + ": " + text for text, who in
            front.doubts(every, taken, by_line=False)]
    said.extend("- " + investigate.STEP + " saw and did not fix: " + l[2:]
                for l in investigate.listed(dug, "RELATED"))
    out.extend(said or ["- none raised"])

    if beside_it:
        out.append("")
        out.append("## found beside the change")
        out.extend("- " + ", ".join(roles) + ": " + f["defect"] + " - "
                   + beside_said(f, files) for f, roles in beside_it)

    if gave:
        out.append("")
        out.append("## reasons")
        out.extend("- " + role + ": " + line for role, lines in gave
                   for line in lines)
        out.append("- " + UNBACKED + ": " + str(len(unheld)))

    ran_checks = checked(every)
    if ran_checks:
        out.append("")
        out.append("## conformance")
        out.extend("- " + at(p) + ": " + c.get("fact", "") + " ("
                   + ", ".join(c.get("scope") or []) + ") "
                   + c.get("result", "") + ": " + c.get("check", "")
                   + (" - " + stops.flat(c["said"]) if c.get("said") else "")
                   for p, c in ran_checks)

    out.append("")
    out.append("## changed")
    out.extend(changed_lines(changes))
    out.extend(unwired)

    out.append("")
    out.append("## read")
    out.extend(read_lines(every))

    out.append("")
    out.append("## tests and checks")
    for p in every:
        if p["gates"]:
            for g in p["gates"]:
                out.append("- " + at(p) + ": " + ("PASS " if g["ok"]
                                                       else "FAIL ")
                           + g["gate"] + (" - " + stops.flat(g["detail"])
                                          if g["detail"] else "")
                           + (" (" + g["command"] + ")" if g["command"]
                              else ""))
        elif p.get("ungated"):
            out.append("- " + at(p) + ": no gates")
    out.extend("- " + stopped["at"] + ": " + ("PASS " if ok else "FAIL ")
               + name + " - " + found
               for name, ok, found in (stopped or {}).get("checked") or [])
    out.append("- red first: " + red_first(every, held))
    out.extend("- " + s for s in sized)
    if order:
        out.append("- test order: " + order)
    if kept:
        out.append("- commits: " + kept)
    out.extend(suite)
    out.extend(signed)
    out.extend("- " + s + " (" + skips.source(s) + ")" for s in skipped)
    _, shown = replay(every)
    if shown is not None:
        from agentweft.guardrails.gates.redfirst_gate import (MISSING_NAME,
                                                              said_of)

        out.extend("- " + said_of(t) + spec_for(t.get("test"), blocks)
                   for t in shown.get("tests") or [])
        red = [t for t in shown.get("tests") or [] if t.get("before") == "red"]
        named = [t for t in red if t.get("red_on") == MISSING_NAME]
        if named:
            out.append("- red on a missing name, not on an assertion: "
                       + str(len(named)) + " of " + str(len(red))
                       + " red without the fix")
    touched = [(path, a, d) for path, a, d, how in changes.get("files", [])
               if is_test(path)]
    if touched:
        out.append("- test files touched: " + "; ".join(
            path + " +" + str(a) + " -" + str(d) for path, a, d in touched))
    if dug.get("REPRO"):
        out.append("- " + investigate.STEP + " repro: "
                   + dug["REPRO"][0].split(":", 1)[1].strip())
    for role, b in blocks:
        if _present(b):
            out.extend("- " + role + " verified: " + handoff.said(i)
                       for i in b["verified"])

    hand = [] if stopped else by_hand(every, proof, changes.get("start"))
    if hand:
        out.append("")
        out.append("## see the fix by hand")
        out.extend(hand)

    out.append("")
    out.append("## rulings")
    owed = rulings(changes, decided, spec_files)
    out.extend(owed or ["- no pre-existing test or spec file changed"])
    out.extend("- on record: " + stamp(d) for d in decided)
    if not decided:
        out.append("- none on record in decisions.md")
    in_run = [d for d in decided if started and d.at >= started]
    out.extend("- authority claimed, no ruling on record: " + l
               for l in authority(blocks, in_run))

    out.append("")
    out.append("## not verified")
    said = ["- " + role + ": " + i for role, b in blocks if _present(b)
            for i in b["not_verified"]]
    said.extend("- " + step + " unproven: " + line for step, line in unsure)
    said.extend("- claims the record does not show: " + role + ": "
                + i["claim"] + " (" + i["why"] + ")"
                for role, b in blocks if _present(b) for i in b["verified"]
                if i["backed"] == "unbacked")
    said.extend(UNSHOWN + role + ": " + r["reason"] + " (led to: "
                + (r["led_to"] or "none named") + ")" for role, r in unheld)
    said.extend("- shortened, so not held to the record: " + role + ": "
                + i["claim"] + " (" + i["cmd"] + ")"
                for role, b in blocks if _present(b) for i in b["verified"]
                if i["backed"] == handoff.SHORTENED)
    from .retro import STEP as RETRO

    for p in every:
        state = p["block"].get("state")
        if state == handoff.MISSING and p["step"] != RETRO:
            said.append("- handoff missing: " + at(p))
        elif state in (handoff.UNREADABLE, handoff.PARTIAL):
            said.append("- handoff " + state + ": " + at(p) + " ("
                        + p["block"].get("why", "") + ")")
    out.extend(said or ["- nothing left unverified, or no step said"])

    if police:
        out.append("")
        out.append("## police")
        out.extend(police)

    out.append("")
    out.append("## carry forward")
    if first_line:
        out.append("- task: " + first_line + " (all of it in runs/" + run_id
                   + "/task.md)")
    out.extend("- keep: " + line + " (" + ", ".join(roles) + ")"
               for line, roles in handoff.keeps(
                   (role, i) for role, b in blocks if _present(b)
                   for i in b["must_not_miss"]))
    for label in ("CAUSE", "SITES", "FEEDS", "RULED OUT"):
        lines = dug.get(label, [])
        if not lines:
            continue
        if label == "CAUSE":
            out.append("- " + investigate.STEP + " " + cause(lines[0]))
        else:
            out.extend("- " + investigate.STEP + " " + label.lower() + ": "
                       + l[2:] for l in investigate.listed(dug, label))
    out.extend("- tried and dropped: " + role + ": " + i for role, b in blocks
               if _present(b) for i in b["tried"])
    if out[-1] == "## carry forward":
        out.append("- nothing beyond the record")

    out.append("")
    out.append("## retro")
    out.extend(retro(every))
    if clock:
        out.append(wall(passes, clock))
        if clock.get("runner"):
            from .laps import said

            out.append(said(clock["runner"]))

    out.append("")
    out.append("## run")
    out.extend(fallen(every))
    if before:
        out.append("- picked up: " + " -> ".join(at(p) for p in before))
    out.append("- steps: " + " -> ".join(
        p["step"] + " " + str(p["seconds"]) + "s"
        + (" (sent back)" if p["outcome"] == "redo" else "")
        for p in passes) if passes else "- steps: none ran")
    out.append("- spend: " + (spend or "0 calls, 0 tokens"))
    out.append("- " + ("cause: " + stopped["cause"] + " at " + stopped["at"]
                       if stopped else outcome(None, unsure)))
    out.append("- record: runs/" + run_id + "/steps.jsonl, gates.jsonl,"
               " gates.md, steps/")
    if chained and chained.get("head"):
        out.append("- chain: " + str(chained["lines"]) + " lines, head "
                   + chained["head"][:16] + " (python run.py verify " + run_id
                   + ")")
    if stopped:
        out.append("")
        out.extend(carry_on(needs, command))
    return out


CARRY_ON = "to carry on"


def carry_on(needs, command):
    """-> the lines a stopped run's handoff ends on: the "to carry on" block
    of its needs section, word for word, so the end of a long handoff is the
    same answer as the top of it. a section with no such block is a run that
    ended on its answer, and nothing carries it on."""
    if needs and CARRY_ON in needs:
        at = len(needs) - 1 - needs[::-1].index(CARRY_ON)
        return [l for l in needs[at:] if l.strip()]
    if needs or not command:
        return ["the run ended here; there is nothing to carry on."]
    return [CARRY_ON, "  " + command]


def settled(decided, passes, run_id):
    """-> the questions a ruling on record answered in this run or a leg
    before it, as points. a ruling another run was given settles nothing
    here."""
    runs = set([run_id] + [p["run"] for p in passes if p.get("run")])
    out = []
    for d in decided or []:
        found = ruling.settled(d)
        if found and found[0] in runs:
            out.append(front.asked_point(found[1]))
    return out


def still_open(passes, stopped):
    """-> the passes whose questions nobody has answered yet: on a stopped
    run, the last pass of the step it stopped at. a finished run has none,
    and a question an earlier pass asked was answered before the run went
    past it, by the lead or with --answer."""
    if not stopped:
        return []
    at = [p for p in passes if p["step"] == stopped["at"]]
    return at[-1:]


def top(lines):
    """-> the lines the console prints last: the default view, everything
    above the full record, and the "needs you" section when there is one."""
    if front.pointer("")[0] in lines:
        cut = lines.index(front.pointer("")[0])
        out = list(lines[:cut])
        if "## needs you" in lines:
            at = lines.index("## needs you")
            end = next((n for n in range(at + 1, len(lines))
                        if lines[n].startswith("## ")), len(lines))
            out.extend(lines[at:end])
        while out and not out[-1].strip():
            out.pop()
        return out
    out = []
    for line in lines:
        if line.startswith("## ") and line != "## needs you":
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def cut_lines(skipped):
    """-> `name: why` for each step the sacrifice list cut."""
    out = []
    for line in skipped:
        if skips.source(line) == "sacrifice":
            names, why = line.split(" skipped: " + skips.BUDGET, 1)
            out.append(names + ": " + why)
    return out


def write(folder, lines):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
