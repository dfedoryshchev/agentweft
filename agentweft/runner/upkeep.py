"""what the retro proposes for the project's facts, and what the runner does
with it.

the retro ends its answer with one typed block, newline sections, never a
`|`:

    FACTS
    fact:
      scope: pkg/a.py
      kind: why
      claim: parse raises on an empty line
      why: the caller counts on the raise
      source: seq 2 worker.md; evidence: pkg/a.py:5 "raise ValueError"
      anchor: pkg/a.py:3-6
    fact:
      scope: README.md
      kind: nice-to-do
      claim: say that `parse` raises on an empty line
      why: the run found the raise undocumented
      source: seq 2 worker.md; evidence: README.md:3 "parse returns a list"
    retire: F-0002
      why: parse no longer has that path
    guard: F-0001
      kind: gate
      where: suite
      what: the suite runs on an empty file too
    END FACTS

`fact`, `supersede: <id>`, `re-anchor: <id>` and `retire: <id>` are done by
the runner, each only once it holds against the record
(`guardrails/factsguard.py`). a `nice-to-do` fact is a ticket for a later
run that touches its one file: the runner changes no file of the tree for
the retro. an `edit: <file>` (`doc:` reads the same; now, after, because)
or a test `guard` (where, what) an older answer still gives is kept as a
ticket on that one file when it can be one, else refused with why into
facts/PROPOSED.md, which keeps nothing else; a gate or flow-key guard is a
proposal line, and so is a test guard for a defect the run left in place:
a defect fact on record it names by id, or the `seq <n>` a defect fact of
the block cites as its source. a block that does not parse writes nothing
and says so in one line; no block at all is nothing to do. what happened to
each item is put in retro.md, on the retro's steps.jsonl line and at the end of
handoff.md, the store files written under a section of their own.

before the retro is asked, the runner writes one fact of its own (`pins`):
the tests the red-first gate ran green without the change, outside the
per-run cap, and a fact of the block that is that note again (one of those
tests named as passing, green or pinning) is refused.

a gate-issue or defect fact proposed again climbs a ladder: in two runs it
is `important`, in three a guard is proposed for it marked `recurring`, and
from four on the handoff lists it as hardening owed, every run, until it is
retired.
"""
import re
from pathlib import Path

from agentweft.guardrails.factsguard import Proposal, seen_of
from agentweft.orchestrate import facts

PASSES = re.compile(r"\b(?:pass(?:es|ed|ing)?|green|pin(?:s|ned|ning)?"
                    r"|without (?:the|this|a|any) (?:change|fix))\b", re.I)
OPEN = re.compile(r"^\s*(?:#+\s*)?FACTS\s*:?\s*$")
CLOSE = re.compile(r"^\s*(?:#+\s*)?END FACTS\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
HEAD = re.compile(r"^(fact|supersede|re-anchor|retire|guard|edit|doc)\s*:"
                  r"\s*(.*?)\s*$")
SUB = re.compile(r"^\s+(?:-\s+)?([a-z][a-z-]*)\s*:\s*(.*?)\s*$")
CODE = re.compile(r"^\s+(?:-\s+)?code:(?: (.*)|)$")
EDITS = ("edit", "doc")
DEFECT = "defect"
SEQ = re.compile(r"^\s*seq\s+(\d+)(?:\s+([^\s;]+))?", re.I)
# the classes of trouble a ladder counts runs of
CLIMBS = ("gate-issue", "defect")
SECTION = "## the retro's proposals"
NO_WRITE = ("the retro changes no file in the tree, and this cannot be a"
            " nice-to-do ticket on one file: ")
CHANGES = "## the retro's changes (unstaged, yours to stage)"
COMMITTED = "## the retro's changes (in their own commit, yours to review)"
DONE_HEAD = "## what the runner did with the FACTS block"


class Maintained(object):
    """what came of one block: facts and tickets written, facts counted and
    changed, each refusal with why, the lines proposed, the hardening owed
    and any note on the block."""

    def __init__(self):
        self.present = False
        self.lines = []
        self.written = []
        self.tickets = []
        self.counted = []
        self.changed = []
        self.refused = []
        self.proposed = 0
        self.owed = []
        self.note = ""
        self.fault = ""
        self.pins = ""
        # each critical ticket put to the lead, and what it decided
        self.escalated = []

    def record(self):
        """-> the `facts` field of the retro's steps.jsonl line."""
        out = {"written": list(self.written), "counted": list(self.counted),
               "changed": list(self.changed),
               "refused": [{"item": what, "why": why}
                           for what, why in self.refused],
               "proposed": self.proposed, "owed": list(self.owed)}
        if self.tickets:
            out["tickets"] = list(self.tickets)
        if self.escalated:
            out["escalated"] = [dict(e) for e in self.escalated]
        if self.pins:
            out["pins"] = self.pins
        if self.note:
            out["block"] = self.note
        if self.fault:
            out["fault"] = self.fault
        return out

    def said(self):
        """-> the lines retro.md and the handoff end on."""
        out = list(self.lines)
        out.extend("- hardening owed: " + o for o in self.owed)
        if self.note:
            out.append("- the FACTS block did not parse: " + self.note
                       + ", so nothing was written")
        if self.fault:
            out.append("- the runner could not finish the FACTS block ("
                       + self.fault + "); the lines above are all it did")
        return out


def parse(text):
    """-> (None, "") for an answer with no block, (None, why) for one that
    does not parse, else ([(verb, its value, {field: value})], "").
    `scope` is a list; the last block in the answer is the one read."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    opens = [n for n, l in enumerate(lines) if OPEN.match(l)]
    if not opens:
        return None, ""
    start = opens[-1]
    end = next((n for n in range(start + 1, len(lines))
                if CLOSE.match(lines[n])), None)
    if end is None:
        return None, "no END FACTS line"
    items = []
    for raw in lines[start + 1:end]:
        code = CODE.match(raw) if items else None
        if code:
            items[-1][2].setdefault("code", []).append(
                (code.group(1) or "").rstrip())
            continue
        if not raw.strip() or FENCE.match(raw):
            continue
        head = HEAD.match(raw)
        if head:
            items.append((head.group(1), head.group(2), {"scope": []}))
            continue
        sub = SUB.match(raw)
        if sub and items:
            key, value = sub.group(1), sub.group(2)
            fields = items[-1][2]
            if key == "scope":
                fields["scope"].append(value)
            elif key not in fields:
                fields[key] = value
            continue
        return None, ('"' + raw.strip()[:80] + '" is neither an item nor one'
                      " of its fields")
    return items, ""


def what_of(verb, value, fields):
    scopes = ", ".join(fields.get("scope") or []) or "no scope"
    return {"fact": "fact on " + scopes,
            "supersede": "supersession of " + value,
            "re-anchor": "re-anchor of " + value,
            "retire": "retirement of " + value,
            "guard": "guard for " + (value or "nothing named"),
            "edit": "doc change to " + (value or "no file"),
            "doc": "doc change to " + (value or "no file")}[verb]


def pins(store, record, found, run_id, today=None):
    """-> (the fact, the line for it) once the runner has written one `why`
    fact labelled `pins` on the test files of `found`, (tests, seq, step):
    the tests the red-first gate ran green without the change. it is held
    to every check a fact is, its evidence the first of those tests' own
    `def` line, and is outside the per-run cap; the store keeps it as
    `pinned`. (None, "") when there are none; (None, why) when refused."""
    tests, seq, step = found
    if not tests or store.off:
        return None, ""
    scopes = sorted(set(t.split("::")[0] for t in tests))
    cite = next((c for c in (def_line(store.root, t) for t in tests) if c),
                None)
    if cite is None:
        return None, ("- the runner kept no note of the tests that pass"
                      " without the change: no `def` line of "
                      + ", ".join(tests) + " was found to cite")
    fields = {"scope": scopes, "kind": "why", "label": facts.PINS,
              "claim": ", ".join(tests) + " pass without the change as well:"
              " they pin what the code did before it and do not prove it",
              "why": "the red-first gate on " + step + " ran each without the"
              " change, and each passed",
              "source": "seq " + str(seq) + " " + step + "; evidence: "
              + cite[0] + ":" + str(cite[1]) + ' "' + cite[2] + '"',
              "anchor": cite[0] + ":" + str(cite[1]) + "-" + str(cite[1])}
    fact, why = store.add(Proposal(fields), record, today,
                          origin="the red-first gate", capped=False)
    if fact is None:
        return None, ("- the runner's note of the tests that pass without the"
                      " change was refused: " + why)
    store.pinned = {"id": fact.id, "scopes": scopes, "tests": list(tests)}
    return fact, ("- the runner wrote " + fact.id + " (" + ", ".join(scopes)
                  + ", why, " + facts.PINS + ") from the red-first gate: "
                  + fact.claim)


def def_line(root, test):
    """-> (file, line number, the line) of the `def` of the test `test`, a
    pytest id, in its file under `root`; None when it is not there."""
    rel, _, rest = test.partition("::")
    name = rest.split("::")[-1].split("[")[0]
    if not name:
        return None
    try:
        lines = (root / rel).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return None
    head = re.compile(r"^\s*(?:async\s+)?def\s+" + re.escape(name) + r"\s*\(")
    for n, line in enumerate(lines, 1):
        if head.match(line):
            return rel, n, line.strip()
    return None


def restates(pinned, fields):
    """-> why a fact the retro proposes is the runner's note of the pinning
    tests again, "" when it is not: it is labelled `pins`, or it is on one
    of that note's test files and its claim names one of its tests and says
    it passes, is green or pins, or holds without the change. another point
    about such a test, a reading of the spec it encodes say, is the
    retro's."""
    if fields.get("label", "").strip() == facts.PINS:
        return ("a pins fact is the runner's own, written from the red-first"
                " gate's record")
    if not pinned:
        return ""
    scopes = [facts.norm(s) for s in fields.get("scope") or []]
    if not set(scopes) & set(pinned["scopes"]):
        return ""
    claim = fields.get("claim", "")
    if not PASSES.search(claim):
        return ""
    for test in pinned["tests"]:
        name = test.split("::")[-1].split("[")[0]
        if name and re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                              claim):
            return ("it restates " + pinned["id"] + ", the runner's note of"
                    " the tests that pass without the change (" + name + ")")
    return ""


def execute(store, record, items, done, run_id, today=None, pins=None):
    """do each item against `store`, noting on `done` what came of it.
    `pins` is the runner's note of the pinning tests (`Store.pinned`), the
    store's when None."""
    if pins is None:
        pins = getattr(store, "pinned", None)
    found = [steps_of(fields.get("source")) for verb, _, fields in items
             if verb in ("fact", "supersede")
             and fields.get("kind", "").strip() == DEFECT]
    for verb, value, fields in items:
        what = what_of(verb, value, fields)
        if verb in ("fact", "supersede"):
            if verb == "supersede":
                fields = dict(fields, supersedes=value)
            why = restates(pins, fields)
            if why:
                refuse(done, what, why)
                continue
            before = store.new + store.tickets_new
            fact, why = store.add(Proposal(fields), record, origin="retro")
            if fact is None:
                refuse(done, what, why)
            else:
                kept(store, done, fact, before, run_id)
        elif verb == "re-anchor":
            why = store.reanchor(value, fields.get("anchor"),
                                 fields.get("evidence"), record, today)
            if why:
                refuse(done, what, why)
            else:
                done.changed.append(value)
                done.lines.append("- anchored " + value + " again on "
                                  + fields.get("anchor", ""))
        elif verb == "retire":
            why = store.retire(value, fields.get("why"), today)
            if why:
                refuse(done, what, why)
            else:
                done.changed.append(value)
                done.lines.append("- retired " + value + ": "
                                  + " ".join(fields.get("why", "").split()))
        elif verb in EDITS:
            edit(store, record, value, fields, done, what, run_id)
        else:
            guard(store, record, value, fields, done, what, run_id,
                  pinned(store, value, found))
    done.owed = owed(store)


def steps_of(said):
    """-> (seq, step or "") a `seq <n> <step>` names at its start, None for
    anything else."""
    m = SEQ.match(said or "")
    return (m.group(1), m.group(2) or "") if m else None


def pinned(store, value, found):
    """-> the defect left in place a guard named `value` is for, "" when it
    names none: a defect fact on record by its id, or the step of this
    block's defect fact (`found`, the (seq, step) of each source)."""
    value = (value or "").strip()
    named = re.match(r"^F-(\d+)$", value, re.I)
    if named:
        value = "F-%04d" % int(named.group(1))
        fact = store.held(value)
        return value + ", a defect on record" \
            if fact is not None and fact.kind == DEFECT else ""
    said = steps_of(value)
    if said is None:
        return ""
    for seq in found:
        if seq is not None and _same(seq, said):
            return ("the defect fact from seq " + seq[0]
                    + (" " + seq[1] if seq[1] else ""))
    return ""


def _same(one, other):
    """whether two (seq, step) pairs name one pass: the same number, and the
    same step when both name one, by its name with case and `.md` dropped."""
    def step(name):
        name = name.lower()
        return name[:-3] if name.endswith(".md") else name

    return int(one[0]) == int(other[0]) and (
        not one[1] or not other[1] or step(one[1]) == step(other[1]))


def refuse(done, what, why):
    done.refused.append((what, why))
    done.lines.append("- refused a " + what + ": " + why)


def one_line(text):
    return " ".join((text or "").split())


def ticket_of(root, verb, value, fields, held=None):
    """-> (the fields of the nice-to-do an edit or a test guard becomes, "")
    or (None, why it cannot be one). an edit's claim is its now and after
    words, its why its because, its evidence the line its now words are on;
    a test guard's claim is the test it asks for, its evidence its own
    `source:` or the source of the fact on record it names (`held`, a fact
    by id). the store holds the rest to a ticket's checks."""
    if verb == "guard":
        rel = facts.norm(fields.get("where") or "")
        source = fields.get("source") or ""
        named = re.match(r"^F-(\d+)$", (value or "").strip(), re.I)
        fact = held("F-%04d" % int(named.group(1))) \
            if named and held is not None and not source else None
        if fact is not None:
            source = fact.get("source")
        return ({"scope": [rel], "kind": facts.NICE,
                 "claim": "add a test: " + one_line(fields.get("what")),
                 "why": one_line(fields.get("why")) or "the test that would"
                 " have caught " + (value or "the run's trouble"),
                 "source": source}, "")
    rel = facts.norm(value or fields.get("file") or "")
    now, after = one_line(fields.get("now")), one_line(fields.get("after"))
    for key, text in (("now", now), ("after", after),
                      ("because", one_line(fields.get("because")))):
        if not text:
            return None, "it has no " + key
    path = Path(root) / rel
    if rel == facts.PROJECT or not path.is_file():
        return None, "a nice-to-do names the one file it is done in"
    lines = facts.text_lines(path)
    bare = now[1:-1] if len(now) > 1 and now[0] == now[-1] \
        and now[0] in "\"'`" else now
    found = next(((n, w) for w in (now, bare)
                  for n, line in enumerate(lines, 1) if w and w in line),
                 None)
    if found is None:
        return None, '"' + now + '" is not in ' + rel
    return ({"scope": [rel], "kind": facts.NICE,
             "claim": 'replace "' + found[1] + '" with "' + after + '"',
             "why": one_line(fields.get("because")),
             "source": "evidence: " + rel + ":" + str(found[0]) + ' "'
             + found[1] + '"'}, "")


def as_ticket(store, record, verb, value, fields, done, what, head, keys,
              run_id):
    """keep an edit or a test guard as a nice-to-do ticket once it can be
    one, else refuse it with why and keep it in facts/PROPOSED.md."""
    ticket, why = ticket_of(store.root, verb, value, fields, store.held)
    fact = None
    if ticket is not None:
        before = store.new + store.tickets_new
        fact, why = store.add(Proposal(ticket), record, origin="retro")
    if fact is None:
        failed(store, done, what, NO_WRITE + why, head, fields, keys)
        return
    kept(store, done, fact, before, run_id)


def kept(store, done, fact, before, run_id):
    """note a fact `store.add` gave back: written new, or counted again."""
    if store.new + store.tickets_new > before:
        done.written.append(fact.id)
        if fact.kind == facts.NICE:
            done.tickets.append(fact.id)
        unchecked = fact.get("unchecked")
        done.lines.append("- wrote " + fact.id + " ("
                          + ", ".join(fact.scopes) + ", " + fact.kind
                          + "): " + fact.claim
                          + (" (kept without its check; " + unchecked + ")"
                             if unchecked else ""))
        return
    if fact.id not in done.counted:
        done.counted.append(fact.id)
        climb(store, fact, done, run_id)
    done.lines.append("- counted " + fact.id + " again (proposed "
                      + str(seen_of(fact)["proposed"]) + ")")


def edit(store, record, value, fields, done, what, run_id):
    """a doc change is never made: it is kept as a nice-to-do ticket on its
    doc, or refused with why into facts/PROPOSED.md."""
    as_ticket(store, record, "edit", value, fields, done, what,
              "## edit " + (value or "no file") + " (" + run_id + ")",
              ("now", "after", "because"), run_id)


def guard(store, record, value, fields, done, what, run_id, defect=""):
    """a test guard is never written: it is kept as a nice-to-do ticket on
    its test file, or refused with why into facts/PROPOSED.md. a gate or
    flow-key guard is a line for a person."""
    kind = fields.get("kind", "").strip()
    said = ("guard (" + kind + ", " + fields.get("where", "") + "): "
            + one_line(fields.get("what")))
    head = "## guard for " + (value or "the run") + " (" + run_id + ")"
    keys = ("kind", "where", "what")
    missing = [k for k in keys if not fields.get(k, "").strip()]
    if missing:
        failed(store, done, what, "it has no " + missing[0], head, fields,
               keys)
        return
    if kind != "test":
        done.proposed = done.proposed + 1
        done.lines.append("- " + said + " (proposed: a " + kind
                          + " guard is the flow's to change)")
        return
    if defect:
        failed(store, done, what, "it guards a defect the run left in place ("
               + defect + "): a test that passes on the tree as left holds"
               " the defect, not its fix", head, fields, keys)
        return
    as_ticket(store, record, "guard", value, fields, done, what, head, keys,
              run_id)


def failed(store, done, what, why, head, fields, keys):
    """an edit or guard that did not hold: refused with why, and kept in
    facts/PROPOSED.md for a person."""
    lines = [head] + [k + ": " + one_line(fields.get(k)) for k in keys
                      if one_line(fields.get(k))]
    if fields.get("code"):
        lines.append("code:")
        lines.extend("    " + line for line in fields["code"])
    kept = store.propose(lines + ["refused: " + why])
    done.refused.append((what, why))
    done.proposed = done.proposed + (0 if kept else 1)
    done.lines.append("- refused a " + what + ": " + why
                      + ("" if kept else " (in facts/PROPOSED.md)"))


def climb(store, fact, done, run_id):
    """the ladder for a gate-issue or defect fact counted again this run."""
    if fact.kind not in CLIMBS:
        return
    runs = seen_of(fact)["proposed"]
    if runs >= 2 and fact.label != "important":
        store.change(fact.id, lambda f: f.put("label", "important"))
        fact.put("label", "important")
    if runs == 3:
        why = store.propose([
            "## guard for " + fact.id + " (" + run_id + ")",
            "recurring: " + fact.id + " seen in 3 runs",
            "kind: test, gate or flow-key, whichever is cheapest",
            "where: " + ", ".join(fact.scopes),
            "what: the program that would have caught: " + fact.claim])
        if not why:
            done.proposed = done.proposed + 1
            done.lines.append("- guard for " + fact.id + ", recurring in 3"
                              " runs (in facts/PROPOSED.md)")


def owed(store):
    """-> a line per live gate-issue or defect fact seen in four runs or
    more."""
    out = []
    for f in store.read():
        if f.status == "live" and f.kind in CLIMBS \
                and seen_of(f)["proposed"] >= 4:
            out.append(f.id + " seen in " + str(seen_of(f)["proposed"])
                       + " runs (" + f.kind + " on " + ", ".join(f.scopes)
                       + "): " + f.claim)
    return out


def maintain(store, record, said, run_id, today=None):
    """-> Maintained for the retro's answer `said`."""
    done = Maintained()
    items, why = parse(said)
    if items is None and not why:
        return done
    done.present = True
    if items is None:
        done.note = why
        return done
    try:
        execute(store, record, items, done, run_id, today)
    except (OSError, ValueError, KeyError, TypeError) as e:
        done.fault = type(e).__name__ + ": " + str(e)
    return done


def files_changed(done, touched, root):
    """-> (path from the place, the line for it) for every store file the
    retro had the runner write, `touched`: no other file is ever changed for
    it."""
    out = []
    ids = set(done.written + done.changed + done.counted)
    for rel in touched:
        name = rel.rsplit("/", 1)[-1]
        if name == facts.INDEX:
            why = "the live facts, listed again"
        elif name == facts.PROPOSED:
            why = "what could not be kept, kept for you"
        else:
            try:
                found = facts.parse((root / rel).read_text(
                    encoding="utf-8"))[1]
            except OSError:
                found = []
            named = [f.id + " " + f.status for f in found if f.id in ids]
            why = ", ".join(named) or "a fact's counts"
        out.append((rel, "- " + rel + ": " + why))
    return out


def tally(run, trail):
    """count on each fact the steps of this leg it was handed, and the steps
    whose change held or broke its check, once the leg has ended: a count
    written while steps run would be a change to the place under them. a
    store that cannot be written is said, never raised."""
    store = getattr(run, "facts", None)
    if store is None or trail is None:
        return []
    lines = [entry.written or {} for entry, _ in trail.closed]
    try:
        out = store.attached(lines)
        for id in (store.held_to(lines, getattr(trail, "folder", None))
                   if hasattr(store, "held_to") else []):
            if id not in out:
                out.append(id)
        return out
    except (OSError, ValueError, KeyError) as e:
        print("facts: attached not counted: " + type(e).__name__ + ": "
              + str(e))
        return []
