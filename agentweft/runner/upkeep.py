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
    retire: F-0002
      why: parse no longer has that path
    edit: README.md
      now: parse returns a list
      after: `parse` returns a list and raises on an empty line
      because: the run found the raise undocumented
    guard: F-0001
      kind: test
      where: tests/test_a_guard.py
      what: an empty line raises ValueError
      code: from pkg.a import parse
      code: ...
    END FACTS

`fact`, `supersede: <id>`, `re-anchor: <id>` and `retire: <id>` are done by
the runner, each only once it holds against the record
(`guardrails/factsguard.py`). an `edit: <file>` (`doc:` reads the same) is
made in the working tree and a test `guard` with `code:` lines (each kept as
written, its indent with it) is written as a new test file, each only once
it holds against the tree as left (`guardrails/retroedits.py`), and neither
is staged. what fails a check is a proposal line with the reason and goes
to facts/PROPOSED.md, which keeps nothing else; a gate or flow-key guard is
a proposal line. a block that does not parse writes nothing and says so in
one line; no block at all is nothing to do. what happened to each item is
put in retro.md, on the retro's steps.jsonl line and at the end of
handoff.md, the files changed under a section of their own.

a gate-issue or defect fact proposed again climbs a ladder: in two runs it
is `important`, in three a guard is proposed for it marked `recurring`, and
from four on the handoff lists it as hardening owed, every run, until it is
retired.
"""
import re

from agentweft.guardrails import retroedits
from agentweft.guardrails.factsguard import Proposal, seen_of
from agentweft.orchestrate import facts

OPEN = re.compile(r"^\s*(?:#+\s*)?FACTS\s*:?\s*$")
CLOSE = re.compile(r"^\s*(?:#+\s*)?END FACTS\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
HEAD = re.compile(r"^(fact|supersede|re-anchor|retire|guard|edit|doc)\s*:"
                  r"\s*(.*?)\s*$")
SUB = re.compile(r"^\s+(?:-\s+)?([a-z][a-z-]*)\s*:\s*(.*?)\s*$")
CODE = re.compile(r"^\s+(?:-\s+)?code:(?: (.*)|)$")
EDITS = ("edit", "doc")
# the classes of trouble a ladder counts runs of
CLIMBS = ("gate-issue", "defect")
SECTION = "## the retro's proposals"
CHANGES = "## the retro's changes (unstaged, yours to stage)"
COMMITTED = "## the retro's changes (in their own commit, yours to review)"
DONE_HEAD = "## what the runner did with the FACTS block"


class Maintained(object):
    """what came of one block: facts written and counted, the files changed
    for it outside facts/, each refusal with why, the lines proposed, the
    hardening owed and any note on the block."""

    def __init__(self):
        self.present = False
        self.lines = []
        self.written = []
        self.counted = []
        self.changed = []
        self.applied = []
        self.refused = []
        self.proposed = 0
        self.owed = []
        self.note = ""
        self.fault = ""

    def kinds(self, *kinds):
        return [a for a in self.applied if a["kind"] in kinds]

    def record(self):
        """-> the `facts` field of the retro's steps.jsonl line."""
        out = {"written": list(self.written), "counted": list(self.counted),
               "changed": list(self.changed),
               "refused": [{"item": what, "why": why}
                           for what, why in self.refused],
               "proposed": self.proposed, "owed": list(self.owed)}
        if self.applied:
            out["applied"] = [dict(a) for a in self.applied]
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


def execute(store, record, items, done, run_id, today=None, keep=None):
    """do each item against `store`, noting on `done` what came of it.
    `keep` makes the edits and guards (`retroedits.Keeper`), one on the
    store's place when None."""
    if keep is None:
        keep = retroedits.Keeper(store.root, own=store.own)
    for verb, value, fields in items:
        what = what_of(verb, value, fields)
        if verb in ("fact", "supersede"):
            if verb == "supersede":
                fields = dict(fields, supersedes=value)
            before = store.new
            fact, why = store.add(Proposal(fields), record, origin="retro")
            if fact is None:
                refuse(done, what, why)
            elif store.new > before:
                done.written.append(fact.id)
                done.lines.append("- wrote " + fact.id + " ("
                                  + ", ".join(fact.scopes) + ", " + fact.kind
                                  + "): " + fact.claim)
            else:
                if fact.id not in done.counted:
                    done.counted.append(fact.id)
                    climb(store, fact, done, run_id)
                done.lines.append("- counted " + fact.id + " again ("
                                  + "proposed "
                                  + str(seen_of(fact)["proposed"]) + ")")
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
            edit(store, record, keep, value, fields, done, what, run_id)
        else:
            guard(store, keep, value, fields, done, what, run_id)
    done.owed = owed(store)


def refuse(done, what, why):
    done.refused.append((what, why))
    done.lines.append("- refused a " + what + ": " + why)


def one_line(text):
    return " ".join((text or "").split())


def edit(store, record, keep, value, fields, done, what, run_id):
    """make the doc change in the working tree once it holds, else propose
    it with why not."""
    rel = facts.norm(value or fields.get("file") or "")
    because = one_line(fields.get("because"))
    why = keep.edit(rel, fields, record) if rel != facts.PROJECT \
        else "it names no file"
    if why:
        failed(store, done, what, why, "## edit " + (value or "no file")
               + " (" + run_id + ")", fields, ("now", "after", "because"))
        return
    kind = retroedits.INSTRUCTION if retroedits.is_instruction(rel) \
        else retroedits.DOC
    store.applied_write(rel, kind, because)
    done.applied.append({"path": rel, "kind": kind, "because": because})
    done.lines.append("- edited " + rel + (" (instruction file touched)"
                                           if kind == retroedits.INSTRUCTION
                                           else "") + ": " + because)


def guard(store, keep, value, fields, done, what, run_id):
    """write a test guard that passes on the tree as left; a gate or
    flow-key guard, or a test with no code, is a line for a person."""
    kind = fields.get("kind", "").strip()
    where = facts.norm(fields.get("where", ""))
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
    why = keep.guard(where, fields)
    if why:
        failed(store, done, what, why, head, fields, keys)
        return
    because = "guard for " + (value or "the run") + ", passes on the tree" \
        " as left: " + one_line(fields.get("what"))
    store.applied_write(where, retroedits.GUARD, because)
    done.applied.append({"path": where, "kind": retroedits.GUARD,
                         "because": because})
    done.lines.append("- wrote the guard " + where + ": " + because)


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


def maintain(store, record, said, run_id, today=None, keep=None):
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
        execute(store, record, items, done, run_id, today, keep)
    except (OSError, ValueError, KeyError, TypeError) as e:
        done.fault = type(e).__name__ + ": " + str(e)
    return done


def files_changed(done, touched, root):
    """-> (path from the place, the line for it) for every file the retro
    had the runner change: instruction files first, then the facts, the
    docs and the guards. `touched` is the store files written for it."""
    out = [(a["path"], "- " + a["path"] + " (instruction file touched): "
            + a["because"]) for a in done.kinds(retroedits.INSTRUCTION)]
    ids = set(done.written + done.changed + done.counted)
    for rel in touched:
        name = rel.rsplit("/", 1)[-1]
        if name == facts.INDEX:
            why = "the live facts, listed again"
        elif name == facts.PROPOSED:
            why = "what failed a check, kept for you"
        else:
            try:
                found = facts.parse((root / rel).read_text(
                    encoding="utf-8"))[1]
            except OSError:
                found = []
            named = [f.id + " " + f.status for f in found if f.id in ids]
            why = ", ".join(named) or "a fact's counts"
        out.append((rel, "- " + rel + ": " + why))
    out.extend((a["path"], "- " + a["path"] + ": " + a["because"])
               for a in done.kinds(retroedits.DOC)
               + done.kinds(retroedits.GUARD))
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
