"""n reports, one verdict.

the role has been in this repo since the workflow file came over.
`agents/architect.md` says it in two lines - "Final judge. When the reviewers
disagree, you decide" - and then spends a table on how: six situations, each
with the ruling it gets, and an output shape with a section for what was raised
and refused. what it has never had is a step.

the flow side's only fan-in is `merge`, and merge is the other thing. it takes
one role's fanned-out parts and is told in so many words not to add anything
that was not already in one of them, which is the right instruction for
stitching and disqualifying for judging: deciding between two reports IS
something neither of them said.

so this is that table, taken out of the prose and put where a step can be held
to it. it is READ off the agent file rather than copied down here. park.py next
door is deliberately not the phase side's mechanism; this one deliberately is,
because a second copy of six rulings is how a repo grows two answers to the
same conflict.

what it does not do is rule. nothing here decides anything: a judge is handed
the reports under their own names, with the table, and what comes back is read
for the shape the file asks for. the half of that file nothing can check is in
UNCHECKED, because a requirement quietly skipped reads exactly like one that
passed.
"""
import re

from . import workflow

JUDGE = "architect.md"
HEAD = "| Situation | Ruling |"

# the agent file answers APPROVED or NEEDS FIXES. the router reads `ok` and
# `redo` off the first line and has since a reviewer could send work back, so a
# judge inside a flow leads with the router's word; read() takes either.
ROUTER = {"APPROVED": "ok", "NEEDS FIXES": "redo", "ok": "ok", "redo": "redo"}

LAST_SECTION = "Deliberately not fixing"

# the file names this one itself: "Both have a point" is not a ruling.
NO_RULING = "both have a point"

UNCHECKED = (
    ("rule on every disagreement",
     "nothing here knows what the disagreements were. they are in the reports, "
     "in prose, which is the reason the reports go to a model at all."),
    ("do not average them",
     "a judgement that split the difference is spelled like one that did not."),
    ("the loop runs at most five times before it is a person's problem",
     "that is `phase.loop`, and the flow side has no word for it. "
     "`workflow.RESIDUE` is where that is written down."),
)

MARKER = re.compile(r"^(?:[-*]|\d+[.)])\s+")
FLAT = re.compile(r"[^a-z0-9+]+")


def _flat(text):
    return FLAT.sub(" ", text.lower()).strip()


class Rule(object):
    """one row of the conflict table: a situation, and the ruling it gets."""

    __slots__ = ("situation", "ruling")

    def __init__(self, situation, ruling):
        self.situation = situation
        self.ruling = ruling

    def __str__(self):
        return self.situation + " -> " + self.ruling


def _cells(line):
    out = [c.strip() for c in line.strip().strip("|").split("|")]
    return out if len(out) == 2 else None


def table(path=None):
    """the conflict table, read off the file that specifies it. -> [Rule].

    empty when there is no such file. a checkout without `orchestrate/` still
    has a judge; what it has not got is the six rulings, and brief() leaves the
    section out rather than sending a heading with nothing under it.
    """
    path = path or (workflow.root() / "agents" / JUDGE)
    if not path.exists():
        return []
    out = []
    started = False
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip() == HEAD:
            started = True
            continue
        if not started:
            continue
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if cells and cells[0].strip("-"):
            out.append(Rule(cells[0], cells[1]))
    return out


class Report(object):
    """one report, and the name of whoever wrote it."""

    __slots__ = ("source", "text")

    def __init__(self, source, text):
        self.source = source
        self.text = text


def brief(reports, rules=None):
    """what a judge is handed. -> the text that goes on the end of its prompt.

    the names are the load-bearing part. "they are not asked to be balanced, so
    do not average them" only means something if the judge can tell whose
    report is whose, and that is exactly what a fan-in that concatenates throws
    away.
    """
    rules = table() if rules is None else rules
    out = ["", "", "here are the reports on the same work, each under the name "
           "of whoever wrote it. they were written from fixed positions, so "
           "they will disagree. do not average them.", ""]
    for report in reports:
        out.append("--- " + report.source + " ---")
        out.append(report.text.strip())
        out.append("")
    if rules:
        out.append("where two of them conflict, the ruling is already decided:")
        out.append("")
        for rule in rules:
            out.append("  " + str(rule))
        out.append("")
    return "\n".join(out)


class Ruling(object):
    """one line of the Rulings section: the conflict, the decision, the rule."""

    __slots__ = ("conflict", "decision", "cited")

    def __init__(self, conflict, decision="", cited=""):
        self.conflict = conflict
        self.decision = decision
        self.cited = cited

    def rule(self, rules=None):
        """which row of the table it says it used. -> Rule, or None.

        matched by containment on either column, both ways round, which is
        forgiving on purpose: "lives in 3+ places" is citing the rule that
        reads "The same logic now lives in 3+ places", and a match that only
        took a row verbatim would be a spelling test wearing a check's name.
        """
        said = _flat(self.cited)
        if not said:
            return None
        for rule in (table() if rules is None else rules):
            for column in (rule.situation, rule.ruling):
                flat = _flat(column)
                if flat and (flat in said or said in flat):
                    return rule
        return None

    def __str__(self):
        return self.conflict + " -> " + self.decision + " -> " + self.cited


class Verdict(object):
    """a judgement, read back: the word it answered and the three sections."""

    __slots__ = ("word", "rulings", "must_fix", "not_fixing", "sections", "raw")

    def __init__(self, word, rulings, must_fix, not_fixing, sections, raw=""):
        self.word = word
        self.rulings = rulings
        self.must_fix = must_fix
        self.not_fixing = not_fixing
        self.sections = sections
        self.raw = raw

    def verdict(self):
        """-> the router's word for it, or "" when it did not answer one."""
        return ROUTER.get(self.word, "")


def _sections(text):
    out = {}
    name = ""
    for line in text.split("\n"):
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
            continue
        if name:
            out[name].append(line)
    return dict((k, "\n".join(v).strip()) for k, v in out.items())


def _items(block):
    out = []
    running = False
    for line in block.split("\n"):
        line = line.strip()
        if MARKER.match(line):
            out.append(MARKER.sub("", line).strip())
            running = True
        elif not line:
            running = False
        elif running:
            # a wrapped item is one item. keeping only its first line would
            # leave the count right and every reason in it half written.
            out[-1] = out[-1] + " " + line
    return out


def _ruling(line):
    parts = [p.strip() for p in line.split("->")]
    return Ruling(parts[0],
                  parts[1] if len(parts) > 1 else "",
                  " -> ".join(parts[2:]) if len(parts) > 2 else "")


def read(text):
    """a judgement as it came back. -> Verdict.

    the word is taken off the first line when it is spelled the way the router
    reads it, and out of the `## Verdict` section otherwise. both, because the
    agent file's own shape puts it in the section and a judge in a flow has to
    put it on the first line for anything to act on it.
    """
    sections = _sections(text)
    first = text.strip().split("\n")[0].strip()
    word = ""
    if first.upper().startswith("VERDICT:"):
        word = first.split(":", 1)[1].strip()
    if not word and sections.get("Verdict"):
        word = sections["Verdict"].split("\n")[0].strip()
    return Verdict(word,
                   [_ruling(i) for i in _items(sections.get("Rulings", ""))],
                   _items(sections.get("Must fix", "")),
                   _items(sections.get(LAST_SECTION, "")),
                   sections, text)


def faults(v, rules=None):
    """what the agent file asks of a judgement and did not get. -> complaints.

    empty means the answer is the shape the file describes, which is not the
    same as the answer being right - UNCHECKED is the rest of the file, and it
    is the larger half.
    """
    rules = table() if rules is None else rules
    bad = []
    if not v.verdict():
        bad.append("no verdict. it is one of: " + ", ".join(sorted(ROUTER)))
    if not v.rulings:
        bad.append("nothing was ruled on")
    for ruling in v.rulings:
        if not ruling.decision:
            bad.append("no decision in: " + ruling.conflict)
        elif rules and ruling.rule(rules) is None:
            bad.append("no rule in the table behind: " + ruling.conflict)
    if NO_RULING in v.raw.lower():
        bad.append('"' + NO_RULING + '" is not a ruling')
    if v.verdict() == "redo" and not v.must_fix:
        bad.append("sent back and named nothing to fix")
    if LAST_SECTION not in v.sections:
        bad.append("no " + LAST_SECTION.lower() + " section. a finding that "
                   "disappears without a reason is raised again next time")
    return bad
