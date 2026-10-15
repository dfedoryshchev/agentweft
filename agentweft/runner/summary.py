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
import re
import subprocess
from pathlib import Path

from agentweft.flow.spec import step_id
from agentweft.guardrails.snapshot import TEST_PATH, is_test  # noqa: F401
from agentweft.guardrails.snapshot import is_spec as spec_path

from . import handoff, investigate, leftred, manifest, stops, verbs

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


def _lines(text):
    return [l.rstrip() for l in (text or "").split("\n") if l.strip()]


def _porcelain(place):
    out = []
    for line in (_git(place, "status", "--porcelain", "--untracked-files=all",
                      "--", ".") or "").split("\n"):
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append((line[:2], path))
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
        the lines each file's change covers, by (path, how), and `status` and
        `log` are what `git status --short` and `git log --oneline
        <start>..HEAD` print, line for line."""
        out = {"git": self.git, "start": self.start, "commits": [],
               "files": [], "tests_changed": [], "spec_changed": [],
               "ranges": {}, "status": [], "log": []}
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
                found = _ranges(_git(self.place, "-c", "core.quotepath=false",
                                     "diff", "--unified=0", "--no-color",
                                     "--no-ext-diff", *(args + ("--", "."))))
                for path, span in found.items():
                    out["ranges"][(path, kind)] = span
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
                lines = (self.root / path).read_bytes().count(b"\n")
            except OSError:
                lines = 0
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


def rulings(changes, decided):
    """the lines a person owes a ruling on, or that one already covers.

    a pre-existing test whose lines were removed or changed, and a spec file
    (`TASK.md`, `SPEC*.md` or under `docs/spec*`, from the top of the
    place) changed at all, each name
    the decisions.md entry behind them or say UNRULED. an add-only test
    change needs none and says so.
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
        found = _ruling_for(path, decided)
        out.append("- spec " + path + " +" + str(a) + " -" + str(d)
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
            for item in block[key]:
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
                # it runs once per new test, so no one name stands for it
                cmd = " ".join(str(a) for a in cmd)
            elif isinstance(cmd, (list, tuple)):
                named = named_test(output or "")
                cmd = " ".join(named if a == "{test}" and named else str(a)
                               for a in cmd)
            out.append(cmd if isinstance(cmd, str) else "")
        return out
    return []


def _gates(results, commands):
    out = []
    for i, g in enumerate(results or []):
        if isinstance(g, dict):
            gate, ok, detail = g.get("gate"), g.get("ok"), g.get("detail")
            unsure = g.get("unproven") or []
            tests = g.get("tests")
        else:
            gate, ok, detail = g.gate, g.ok, g.detail
            unsure = g.unproven
            tests = getattr(g, "tests", None)
        kept = {"gate": gate, "ok": bool(ok), "detail": detail or "",
                "command": commands[i] if i < len(commands) else "",
                "tests": tests}
        if unsure:
            kept["unproven"] = list(unsure)
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


def _redo_why(said):
    for line in handoff.without(said or "").split("\n"):
        if line.strip() and not line.strip().upper().startswith("VERDICT:"):
            return line.strip()
    return ""


def a_pass(step, role, seconds, block, gates, ungated, outcome, said,
           facts=None):
    """one pass of one step, the shape `build` reads. `facts` is what its
    steps.jsonl line holds for the retro and the files its transcript shows
    it read (`facts_of`)."""
    return {"step": step, "role": role, "seconds": seconds,
            "block": block if isinstance(block, dict) else handoff.empty(),
            "gates": gates, "ungated": ungated, "outcome": outcome,
            "verbs": verbs.parse(said),
            "redo_why": _redo_why(said) if outcome == "redo" else "",
            "facts": facts or {}}


RETRO = ("cost", "cost_from", "cached", "retries", "background_killed",
         "shell_writes_denied", "shell_trap_recoveries")


def read_of(sessions, root=None):
    """-> [(path, range)] the sessions' transcripts show read, None when not
    one of them has a transcript."""
    out = None
    for session in sessions:
        found = handoff.reads(session, root)
        if found is not None:
            out = (out or []) + found
    return out


def facts_of(line, root=None):
    """-> a pass's facts from its steps.jsonl line: the retro's fields, and
    what its sessions read, from `root` when the path is under it."""
    out = dict((k, line.get(k)) for k in RETRO)
    sessions = [line["session"]] if line.get("session") else []
    sessions.extend(t["session"] for t in (line.get("tasks") or [])
                    if isinstance(t, dict) and t.get("session"))
    out["read"] = read_of(sessions, root)
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
    for raw in path.read_text(encoding="utf-8").split("\n"):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        step = line.get("step")
        said = ""
        kept = line.get("file")
        if kept and (folder / kept).is_file():
            said = (folder / kept).read_text(encoding="utf-8")
        out.append(a_pass(step, roles.get(step, step),
                          line.get("seconds") or 0, line.get("handoff"),
                          _gates(line.get("gates"),
                                 gate_commands(fm, step, said)),
                          line.get("ungated"), line.get("outcome") or "",
                          said, facts=facts_of(line, root)))
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
            if g["gate"] == "red-first" and \
                    not g["detail"].startswith("not replayed"):
                return p["step"], g
    return None, None


def red_first(passes):
    step, g = replay(passes)
    if g is not None:
        if not g["ok"]:
            return "the red-first gate failed on " + step + ": " + g["detail"]
        return "shown on " + step + ", " + g["detail"]
    for p in passes:
        for g in p["gates"]:
            if g["gate"] != "red-test" or not g["detail"].startswith("red"):
                continue
            if not g["ok"]:
                return "the red-test gate failed on " + at(p) + ": " \
                    + g["detail"]
            if "nothing was run" in g["detail"]:
                return "claimed by " + at(p) + ", nothing was run"
            return ("gate-proven on " + at(p) + " (" + g["detail"]
                    + (", " + g["command"] if g["command"] else "") + ")")
    return "not proven by a gate"


def assumed(item):
    choice, why, cost = item, "", ""
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


def ended(stopped, unsure=()):
    """-> the words after the run id: the outcome first, then for a stop
    where and why."""
    out = outcome(stopped, unsure)
    if not stopped:
        return out
    why = stopped.get("why") or ""
    out = out + " at " + stopped["at"]
    return out + (" - " + stops.flat(why) if why else "")


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
    gates it failed, its retries, the limit and refusals it met, the shell
    trouble it recovered from; then one line per send-back with why."""
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
        out.append("- " + at(p) + " " + str(took) + "s ("
                   + _money(f) + "): " + ("; ".join(said) or "no events"))
    out.extend("- " + p["step"] + " sent the work back: " + p["redo_why"]
               for p in passes if p["outcome"] == "redo" and p["redo_why"])
    return out or ["- no step ran"]


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
          found="", order="", left=None):
    """-> the lines of handoff.md.

    `passes` is this run's passes in order and `before` the ones of the run
    it picked up, if any; `changes` is `Tree.changes()`; `decided` is every
    decisions.md entry in the place; `stopped` is {"cause", "why", "at"} for
    a run that stopped short; `needs` is the park section's lines when the
    run waits for someone; `command` is the line that carries on; `found` is
    the investigator's answer when the flow ran one; `order` is the line on
    the red test the run holds before product code, "" for none; `left` is
    what a stop found of the tests the run added or changed (`leftred.check`).
    """
    every = list(before) + list(passes)
    blocks = [(p["role"], p["block"]) for p in every]
    last = working(every)
    dug = investigate.sections(found)
    first_line = (task or "").strip().split("\n")[0] if task else ""
    unsure = unproven(every)
    out = ["# " + flow_name + " " + run_id + ": " + ended(stopped, unsure)]
    if last and last["block"]["did"]:
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
    if last:
        out.append(last["role"] + " did:")
        out.extend("- " + i for i in did_of(every, last["role"]))
    else:
        out.append("no step handed over a block, so what was done is only"
                   " what git and the gates show below.")
    gates = [g for p in every for g in p["gates"]]
    passed = sum(1 for g in gates if g["ok"])
    checks = (str(passed) + " of " + str(len(gates)) + " gates passed"
              if gates else "no gates ran")
    out.append("checks: " + checks + "; red first: " + red_first(every)
               + ("; " + order if order.startswith("tests skipped") else "")
               + ".")
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

    asked = asks(every)
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

    out.append("")
    out.append("## assumed - tell me if wrong")
    said = ["- " + role + ": " + assumed(i) for role, b in blocks
            if _present(b) for i in b["assumed"]]
    out.extend(said or ["- nothing assumed, or no step said"])

    out.append("")
    out.append("## doubts")
    said = ["- " + role + ": " + i for role, b in blocks if _present(b)
            for i in b["doubts"]]
    said.extend("- " + investigate.STEP + " saw and did not fix: " + l[2:]
                for l in investigate.listed(dug, "RELATED"))
    out.extend(said or ["- none raised"])

    out.append("")
    out.append("## changed")
    out.extend(changed_lines(changes))

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
    out.append("- red first: " + red_first(every))
    if order:
        out.append("- test order: " + order)
    _, shown = replay(every)
    if shown is not None:
        from agentweft.guardrails.gates.redfirst_gate import said_of

        out.extend("- " + said_of(t) + spec_for(t.get("test"), blocks)
                   for t in shown.get("tests") or [])
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

    out.append("")
    out.append("## rulings")
    owed = rulings(changes, decided)
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
    for p in every:
        state = p["block"].get("state")
        if state == handoff.MISSING:
            said.append("- handoff missing: " + at(p))
        elif state in (handoff.UNREADABLE, handoff.PARTIAL):
            said.append("- handoff " + state + ": " + at(p) + " ("
                        + p["block"].get("why", "") + ")")
    out.extend(said or ["- nothing left unverified, or no step said"])

    out.append("")
    out.append("## carry forward")
    if first_line:
        out.append("- task: " + first_line + " (all of it in runs/" + run_id
                   + "/task.md)")
    kept = []
    for role, b in blocks:
        if _present(b):
            for i in b["must_not_miss"]:
                if i not in kept:
                    kept.append(i)
                    out.append("- keep: " + i + " (" + role + ")")
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

    out.append("")
    out.append("## run")
    if before:
        out.append("- picked up: " + " -> ".join(at(p) for p in before))
    out.append("- steps: " + " -> ".join(
        p["step"] + " " + str(p["seconds"]) + "s"
        + (" (sent back)" if p["outcome"] == "redo" else "")
        for p in passes) if passes else "- steps: none ran")
    out.append("- spend: " + (spend or "0 calls, 0 tokens"))
    out.append("- " + ("cause: " + stopped["cause"] + " at " + stopped["at"]
                       if stopped else outcome(None, unsure)))
    out.append("- record: runs/" + run_id + "/steps.jsonl, gates.md, steps/")
    if stopped and command:
        # the file ends on the line to type, so the end of a long handoff is
        # the same answer as the top of it
        out.append("")
        out.append("to carry on")
        out.append("  " + command)
    return out


def top(lines):
    """-> the lines the console prints last: the heading, the prose, and the
    "needs you" section when there is one."""
    out = []
    for line in lines:
        if line.startswith("## ") and line != "## needs you":
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def write(folder, lines):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
