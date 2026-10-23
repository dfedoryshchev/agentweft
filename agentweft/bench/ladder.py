"""a run's handoff scored on a ten-point ladder, one named line per point.

the strict 0-3 handoff score is 3 on every run once the runner fills what
changed, how it was checked and one doubt on every path, so it tells nothing
apart. the ladder does: each point is a line a person picking the run up
cold needs, and each is held by a program over handoff.md as the run wrote
it, never by a model. a point the run's path has no such line for, tests on
a conflict stop, is not applicable: it is left out of the score, never 0.

the score is the points held over the points that apply, out of ten. runs
are grouped by path (done, stopped, parked, failed), each with its mean and
how often each point was missed.

the first point can hold the handoff only to its own record unless the
hidden suite's verdict on the tree is given (`--hidden`): without it the
point is named `outcome consistent`, with it `outcome true`.
"""
import json
import re
from pathlib import Path

from agentweft.runner import front, stops

FILE = "handoff.md"
DONE, STOPPED, PARKED, FAILED = "done", "stopped", "parked", "failed"
PATHS = (DONE, STOPPED, PARKED, FAILED)
# a first line with no outcome word on it: nothing on the page can be held
UNREAD = "unread"
FAILED_AS = (stops.outcome(stops.GATE), stops.outcome(stops.EXCEPTION),
             stops.outcome(stops.INTERRUPT))
TRUE = "outcome true"
POINTS = (("outcome", "outcome consistent"),
          ("decision", "the one decision first and right"),
          ("changed", "changed, from git"),
          ("read", "read, with the line that mattered"),
          ("tests", "tests red then green"),
          ("checks", "checks backed"),
          ("why", "why in one section"),
          ("not_done", "not done said plainly"),
          ("no_false", "no false line"),
          ("once", "once, for everyone"))

HEAD = re.compile(r"^# \S+ \S+: (.*)$")
WORD_DONE = re.compile(r"^done(?:, \d+ checks? unproven)?")
CAUSE = re.compile(r"^- cause: (.+) at (\S+)$")
CITE = re.compile(r"[\w./-]+\.\w+:\d+(?:-\d+)?")
ESCALATED = re.compile(r"the flow's lead did not decide it: (\S+?)(?:\.md)?"
                       r" escalated it")
TEST_LINE = re.compile(r"^- \S+::\S+: .*? without the fix.*?, (\w+) with it")
VERIFIED = re.compile(r"^- \S+ verified: .* -> (\w+)(?: by (\w+))?")
# the kinds of call a backed line can name; a record from before they were
# named keeps its lines as "not named"
BY = ("command", "stdin", "read", "file", "not named")
ROLE_ITEM = re.compile(r"^- ([\w.-]+): (.+)$")
PLAIN = re.compile(r"^- (not done|not fixed|left undone)\b", re.I)
EDITS = re.compile(r"^- \S+: PASS (?:spec-files|test-edits) - (\S+?): .*"
                   r"(?:none the run started with changed|no line the run"
                   r" started with removed or changed)")
REPEATED_IN = ("open questions", "assumed - tell me if wrong", "doubts")
PROVEN = ("shown on ", "gate-proven on ")


def parse(text):
    """-> (head lines, {section: lines}, section names in order); a section
    named twice keeps its first."""
    head, secs, order, now = [], {}, [], None
    for line in (text or "").split("\n"):
        if line.startswith("## "):
            now = line[3:].strip()
            if now in secs:
                now = None
                continue
            secs[now] = []
            order.append(now)
        elif now is not None:
            secs[now].append(line)
        elif not order:
            head.append(line)
    return head, secs, order


def outcome_of(head):
    """-> (the outcome word, what follows it) off the first line."""
    m = HEAD.match(head[0] if head else "")
    if not m:
        return None, ""
    rest = m.group(1)
    found = WORD_DONE.match(rest)
    if found:
        return found.group(0), rest[found.end():]
    for word in sorted(stops.OUTCOMES, key=len, reverse=True):
        if rest.startswith(word):
            return word, rest[len(word):]
    return None, rest


def path_of(word):
    if word is None:
        return UNREAD
    if WORD_DONE.match(word):
        return DONE
    if word.startswith(("needs you", "waiting")):
        return PARKED
    if word in FAILED_AS:
        return FAILED
    return STOPPED


def items(lines):
    """-> [(the "- " line, [the indented lines under it])]."""
    out = []
    for line in lines:
        if line.startswith("- "):
            out.append((line, []))
        elif line.startswith("  ") and out:
            out[-1][1].append(line.strip())
    return out


def score(text, correct=None):
    """-> {"path", "outcome", "points": [{"point", "name", "got", "line"}],
    "earned", "applicable", "score"} for a handoff's text. `got` is 1, 0, or
    None when the point does not apply to the run's path. `correct` is what
    the hidden suite found of the tree, when a bench knows it: a done word
    on a tree it finds red is not a true outcome."""
    head, secs, order = parse(text)
    word, rest = outcome_of(head)
    path = path_of(word)
    marks = {}
    if path == UNREAD:
        marks = dict((p, (0, "the first line names no outcome word"))
                     for p, _ in POINTS)
    else:
        ctx = {"text": text, "head": head, "secs": secs, "order": order,
               "word": word, "rest": rest, "path": path, "correct": correct}
        for point, _ in POINTS:
            marks[point] = CHECKS[point](ctx)
    out = []
    for point, name in POINTS:
        got, line = marks[point]
        if point == "outcome" and correct is not None:
            name = TRUE
        out.append({"point": point, "name": name, "got": got, "line": line})
    held = [p["got"] for p in out if p["got"] is not None]
    earned = sum(held)
    return {"path": path, "outcome": word, "points": out, "earned": earned,
            "applicable": len(held),
            "score": round(10.0 * earned / len(held), 1) if held else 0,
            "backing": backing(secs)}


def backing(secs):
    """-> {kind: how many verified lines it backs} off the tests and checks
    section, every kind in BY named, 0 for none."""
    out = dict((k, 0) for k in BY)
    for l in secs.get("tests and checks", []):
        m = VERIFIED.match(l)
        if m and m.group(1) == "backed":
            kind = m.group(2) if m.group(2) in BY else "not named"
            out[kind] += 1
    return out


def by_kind(counts):
    """-> "command 1, read 2": the kinds that back a line, in BY's order."""
    return ", ".join(k + " " + str(counts[k]) for k in BY if counts.get(k))


def _outcome(c):
    if c["path"] != DONE and not c["rest"].strip(" -"):
        return 0, "a stop that names no cause after " + c["word"]
    said = [l for l in c["secs"].get("run", []) if l.startswith("- ")]
    cause = next((CAUSE.match(l) for l in said if CAUSE.match(l)), None)
    if c["path"] == DONE:
        if cause:
            return 0, "the first line says done, the run section " + \
                cause.group(0)[2:]
        if c["correct"] is False:
            return 0, "done, while the hidden suite finds the tree red"
        return 1, c["word"] + ", and the run section agrees"
    if cause is None:
        return 0, "a stop whose run section names no cause"
    try:
        named = stops.outcome(cause.group(1))
    except ValueError:
        return 0, "the run section's cause " + cause.group(1) + " is not one"
    if named != c["word"]:
        return 0, ("the first line says " + c["word"] + ", the cause "
                   + cause.group(1) + " is " + named)
    return 1, c["word"] + " at " + cause.group(2) + ", as the record names it"


def _decision(c):
    if not c["order"] or c["order"][0] != "the one decision":
        return 0, "the one decision is not the first section"
    found = items(c["secs"]["the one decision"])
    if len(found) != 1:
        return 0, str(len(found)) + " items under the one decision, not one"
    item, under = found[0]
    if item.startswith("- none"):
        if c["path"] == DONE:
            return 1, "none, on a done run"
        return 0, "none, on a run that stopped"
    if item.lower().startswith("- decided"):
        return 1, item[2:]
    ruled = [l for l in c["secs"].get("rulings", [])
             if l.startswith("- on record:")]
    if c["path"] == DONE and ruled:
        return 0, ("a question shown open on a done run with a ruling on"
                   " record: " + ruled[0][len("- on record: "):])
    rec = next((l for l in under if l.startswith("recommendation")), "")
    lead = ESCALATED.search(c["text"])
    if lead and not rec.startswith("recommendation (" + lead.group(1)):
        return 0, ("the lead, " + lead.group(1) + ", escalated it with its"
                   " own recommendation, and the one decision shows another")
    if not rec and c["path"] != DONE and item[2:].startswith(c["word"]) \
            and (front.CARRY in under or front.DECLINED in under):
        cause = next((CAUSE.match(l).group(1) for l in
                      c["secs"].get("run", []) if CAUSE.match(l)), None)
        if cause in front.ADVISED:
            return 0, ("a " + cause + " stop with no recommendation, while"
                       " its cause gives one")
        return 1, "the stop is the decision, with what carries it on"
    if not rec:
        return 0, "no recommendation line"
    if "none given" in rec and any(
            "recommendation: " in l and "none given" not in l
            for l in c["text"].split("\n")):
        return 0, "recommendation: none given, while the record holds one"
    if c["path"] == PARKED and "--resume" not in c["text"]:
        return 0, "a park with no command to carry it on"
    return 1, rec


def _changed(c):
    lines = c["secs"].get("changed")
    if lines is None:
        return 0, "no changed section"
    if any("not a git checkout" in l for l in lines):
        return None, "not a git checkout"
    files = [l for l in lines
             if re.match(r"^- \S+ \+\d+ -\d+ \((?:committed|uncommitted|"
                         r"untracked|[\w ,]+)\)", l)]
    if files:
        return 1, str(len(files)) + " files with lines and commit state"
    if any(l.startswith("- nothing changed") for l in lines):
        return 1, "nothing changed in the tree"
    return 0, "no file with its lines and commit state"


def _read(c):
    found = items(c["secs"].get("read", []))
    passes = [(i, u) for i, u in found if " read: " in i
              or i.endswith(" read no file, by its transcript")]
    if not passes:
        return 0, "no pass with the files it read"
    bare = [i for i, u in passes if " read: " in i
            and not any(l.startswith("said") for l in u)]
    if bare:
        return 0, ("read with no line that mattered: "
                   + bare[0][2:].split(" read: ")[0])
    return 1, str(len(passes)) + " passes, each with what it read and said"


def _tests(c):
    lines = c["secs"].get("tests and checks", [])
    tests = [TEST_LINE.match(l) for l in lines if TEST_LINE.match(l)]
    touched = tests or any(l.startswith("- test files touched:")
                           for l in lines)
    if not touched:
        if c["path"] != DONE:
            return None, "no test written on a run that stopped"
        return 0, "a done run with no new test"
    red = next((l[len("- red first: "):] for l in lines
                if l.startswith("- red first: ")), "")
    if not red.startswith(PROVEN):
        return 0, "red first: " + (red or "no line")
    after = [m.group(1) for m in tests if m.group(1) != "green"]
    if after:
        return 0, str(len(after)) + " new tests not green with the fix"
    if any(l.startswith("- ") and ": FAIL start-tests" in l for l in lines):
        return 0, "a test the run started with is red now"
    return 1, str(len(tests)) + " tests red then green; red first " + red[:40]


def _checks(c):
    lines = c["secs"].get("tests and checks", [])
    gates = [l for l in lines if re.match(r"^- \S+: (?:PASS|FAIL) ", l)]
    said = [VERIFIED.match(l).group(1) for l in lines if VERIFIED.match(l)]
    unchecked = said.count("unchecked")
    held = [s for s in said if s != "unchecked"]
    if not gates and not held:
        return None, ("no gate ran and no step said it verified" if not said
                      else str(unchecked) + " verified line"
                      + ("" if unchecked == 1 else "s") + " unchecked, no"
                      " transcript to hold them to, and no gate ran")
    bad = [s for s in held if s != "backed"]
    if bad:
        return 0, (str(len(bad)) + " verified lines the record does not back"
                   " (" + ", ".join(sorted(set(bad))) + ")")
    kinds = backing(c["secs"])
    return 1, (str(len(gates)) + " gates, " + str(len(held))
               + " verified line" + ("" if len(held) == 1 else "s") + " backed"
               + (" (by " + by_kind(kinds) + "; " + str(kinds["command"])
                  + " of " + str(len(held)) + " by a command alone)"
                  if held else "")
               + (", " + str(unchecked) + " unchecked, not counted"
                  if unchecked else ""))


def _why(c):
    lines = [l for l in c["secs"].get("why", []) if l.strip()]
    if not lines or any("no step handed over a block" in l for l in lines):
        return 0, "no why: no step said what it did"
    tried = [l for l in c["text"].split("\n")
             if l.startswith("- tried and dropped:")]
    if tried and not any("tried and dropped" in l or "ruled out" in l
                         for l in lines):
        return 0, (str(len(tried)) + " alternatives tried and dropped sit"
                   " outside the why section")
    return 1, "the cause and the fix" + (" against the alternatives"
                                         if tried else "") + " in one section"


def _not_done(c):
    lines = c["secs"].get("not done")
    if lines is None or not any(l.strip() for l in lines):
        return 0, "no not done section"
    if c["path"] == DONE:
        return 1, "said, on a done run"
    if any(PLAIN.match(l) for l in lines):
        return 1, next(l for l in lines if PLAIN.match(l))[2:]
    return 0, "a stop that does not say in a line of its own what is not done"


def _no_false(c):
    text, secs = c["text"], c["secs"]
    changed = [l[2:].split(" ")[0] for l in secs.get("changed", [])
               if re.match(r"^- \S+ \+\d+ -\d+ \(", l)]
    product = [f for f in changed if not _test_file(f) and not
               f.lower().endswith(".md")]
    if "instead of doing the work" in text and product:
        return 0, ("says it asked instead of doing the work, and the tree"
                   " holds " + product[0])
    allowed = [m.group(1) for m in (EDITS.match(l) for l in
                                    secs.get("tests and checks", [])) if m]
    for l in secs.get("rulings", []):
        if "UNRULED" in l and any(a in l for a in allowed):
            return 0, "UNRULED on an addition a gate allowed: " + l[2:]
    red = " ".join(l for l in c["head"] + secs.get("tests and checks", [])
                   if "red first" in l)
    if "gate-proven" in red and not any(
            re.match(r"^- \S+: PASS red-(?:test|first) - red", l)
            for l in secs.get("tests and checks", [])):
        return 0, "gate-proven, with no red gate that went red"
    ruled = any(l.startswith("- on record:") for l in secs.get("rulings", []))
    open_ = [i for i, _ in items(secs.get("the one decision", []))
             if not i.startswith("- none") and
             not i.lower().startswith("- decided")]
    if c["path"] == DONE and ruled and open_:
        return 0, "a decided question shown open"
    return 1, "none of the known false lines"


def _once(c):
    for name in REPEATED_IN:
        seen = {}
        for line in c["secs"].get(name, []):
            m = ROLE_ITEM.match(line)
            if not m:
                continue
            for cite in set(CITE.findall(m.group(2))):
                seen.setdefault(cite, []).append(m.group(1))
        twice = sorted((cite, roles) for cite, roles in seen.items()
                       if len(roles) > 1)
        if twice:
            cite, roles = twice[0]
            return 0, (name + ": " + str(len(roles)) + " entries on " + cite
                       + " (" + ", ".join(roles) + ")")
    lines = c["secs"].get("tests and checks", [])
    if c["path"] == DONE and any(TEST_LINE.match(l) for l in lines):
        hand = c["secs"].get("see the fix by hand", [])
        if not any(l.startswith("    ") and l.strip() for l in hand):
            return 0, "new tests and no command to see the fix by hand"
    return 1, "each open point and assumption once"


def _test_file(path):
    from agentweft.guardrails.snapshot import is_test

    return is_test(path)


CHECKS = {"outcome": _outcome, "decision": _decision, "changed": _changed,
          "read": _read, "tests": _tests, "checks": _checks, "why": _why,
          "not_done": _not_done, "no_false": _no_false, "once": _once}


def score_run(folder, correct=None):
    """-> the ladder of the run whose record is `folder`, None when it holds
    no handoff.md."""
    path = Path(folder) / FILE
    if not path.is_file():
        return None
    got = score(path.read_text(encoding="utf-8", errors="replace"), correct)
    got["run"] = Path(folder).name
    return got


def runs_in(folders):
    """-> every folder at or under `folders` that holds a handoff.md."""
    out = []
    for f in folders:
        f = Path(f)
        if (f / FILE).is_file():
            out.append(f)
        elif f.is_dir():
            out.extend(sorted(p.parent for p in f.rglob(FILE)))
    return out


def _num(n):
    return int(n) if n == int(n) else n


def summary(rows):
    """-> {path: {"runs", "mean", "missed": {point: n}, "not_applicable":
    {point: n}}} for the paths the rows hold."""
    out = {}
    for path in PATHS + (UNREAD,):
        mine = [r for r in rows if r["path"] == path]
        if not mine:
            continue
        missed = dict((p, 0) for p, _ in POINTS)
        skipped = dict((p, 0) for p, _ in POINTS)
        for r in mine:
            for p in r["points"]:
                if p["got"] == 0:
                    missed[p["point"]] += 1
                elif p["got"] is None:
                    skipped[p["point"]] += 1
        kinds = dict((k, sum(r.get("backing", {}).get(k, 0) for r in mine))
                     for k in BY)
        out[path] = {"runs": len(mine),
                     "mean": _num(round(sum(r["score"] for r in mine)
                                        / float(len(mine)), 1)),
                     "missed": missed, "not_applicable": skipped,
                     "backing": kinds}
    return out


def lines(scored):
    """-> one run's ladder as lines: its path and score, then a named line
    per point."""
    out = [(scored.get("run") or "handoff") + " (" + scored["path"] + "): "
           + (scored["outcome"] or "no outcome word") + ", "
           + str(_num(scored["score"])) + "/10"]
    for n, p in enumerate(scored["points"]):
        mark = {1: "yes", 0: "no", None: "n/a"}[p["got"]]
        out.append("  " + str(n + 1) + " " + p["name"] + ": " + mark + " - "
                   + p["line"])
    return out


def table(rows):
    """-> the report: each run's ladder, then each path's mean and the
    points it missed."""
    out = []
    for r in rows:
        out.extend(lines(r))
        out.append("")
    for path, s in summary(rows).items():
        missed = ", ".join(name + " " + str(s["missed"][p])
                           for p, name in POINTS if s["missed"][p])
        out.append(path + ": " + str(s["runs"]) + " run"
                   + ("" if s["runs"] == 1 else "s") + ", mean "
                   + str(s["mean"]) + ", missed " + (missed or "none")
                   + ", verified lines backed by "
                   + (by_kind(s["backing"]) or "none"))
    return "\n".join(out)


def verdicts(path):
    """-> {run folder name: whether the hidden suite found its tree green}
    read from the JSON file at `path`. ValueError when it does not read as
    that: a verdict that cannot be read is never taken as none."""
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("--hidden " + str(path) + " does not read: " + str(e))
    if not isinstance(got, dict) or not all(
            isinstance(v, bool) for v in got.values()):
        raise ValueError("--hidden " + str(path) + " has to map each run"
                         " folder's name to true or false")
    return got


def main(argv, valued=None, fake=None):
    """`--ladder <folder>... [--hidden <file>]`: each run folder at or under
    them scored. `--hidden` names a JSON file of the hidden suite's verdicts,
    by run folder name: a run it names has its first point held to it."""
    at = argv.index("--ladder")
    folders, skip = [], False
    for a in argv[at + 1:]:
        if skip or a.startswith("--"):
            skip = a == "--hidden"
            continue
        folders.append(a)
    if not folders:
        raise ValueError("--ladder needs a run folder, or a folder of them")
    hidden = valued(argv, "--hidden") if valued else None
    known = verdicts(hidden) if hidden is not None else {}
    found = runs_in(folders)
    if not found:
        print("no handoff.md at or under " + ", ".join(folders)
              + ": nothing to score")
        return 1
    print(table([score_run(f, known.get(Path(f).name)) for f in found]))
    return 0
