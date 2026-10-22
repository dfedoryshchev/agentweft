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
    guard: F-0001
      kind: test
      where: tests/test_a.py
      what: an empty line raises ValueError
    END FACTS

`fact`, `supersede: <id>`, `re-anchor: <id>` and `retire: <id>` are done by
the runner, each only once it holds against the record
(`guardrails/factsguard.py`). `guard: <id or seq n>` and `doc: <file>` are
proposals: appended to facts/PROPOSED.md and listed in the handoff, never
applied. a block that does not parse writes nothing and says so in one
line; no block at all is nothing to do. what happened to each item is put
in retro.md, on the retro's steps.jsonl line and at the end of handoff.md.

a gate-issue or defect fact proposed again climbs a ladder: in two runs it
is `important`, in three a guard is proposed for it marked `recurring`, and
from four on the handoff lists it as hardening owed, every run, until it is
retired.
"""
import re

from agentweft.guardrails.factsguard import Proposal, seen_of

OPEN = re.compile(r"^\s*(?:#+\s*)?FACTS\s*:?\s*$")
CLOSE = re.compile(r"^\s*(?:#+\s*)?END FACTS\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
HEAD = re.compile(r"^(fact|supersede|re-anchor|retire|guard|doc)\s*:\s*(.*?)"
                  r"\s*$")
SUB = re.compile(r"^\s+(?:-\s+)?([a-z][a-z-]*)\s*:\s*(.*?)\s*$")
# the classes of trouble a ladder counts runs of
CLIMBS = ("gate-issue", "defect")
SECTION = "## the retro's proposals"
DONE_HEAD = "## what the runner did with the FACTS block"


class Maintained(object):
    """what came of one block: facts written and counted, each refusal with
    why, the lines proposed, the hardening owed and any note on the block."""

    def __init__(self):
        self.present = False
        self.lines = []
        self.written = []
        self.counted = []
        self.changed = []
        self.refused = []
        self.proposed = 0
        self.owed = []
        self.note = ""
        self.fault = ""

    def record(self):
        """-> the `facts` field of the retro's steps.jsonl line."""
        out = {"written": list(self.written), "counted": list(self.counted),
               "changed": list(self.changed),
               "refused": [{"item": what, "why": why}
                           for what, why in self.refused],
               "proposed": self.proposed, "owed": list(self.owed)}
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
            "doc": "doc change to " + (value or "no file")}[verb]


def execute(store, record, items, done, run_id, today=None):
    """do each item against `store`, noting on `done` what came of it."""
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
        else:
            proposal(store, verb, value, fields, done, what, run_id)
    done.owed = owed(store)


def refuse(done, what, why):
    done.refused.append((what, why))
    done.lines.append("- refused a " + what + ": " + why)


def proposal(store, verb, value, fields, done, what, run_id):
    if verb == "guard":
        keys = ("kind", "where", "what")
        head = "## guard for " + (value or "the run") + " (" + run_id + ")"
        line = ("- guard (" + fields.get("kind", "") + ", "
                + fields.get("where", "") + "): " + fields.get("what", ""))
    else:
        keys = ("now", "after", "because")
        head = "## doc " + value + " (" + run_id + ")"
        line = "- doc " + value + ": " + fields.get("after", "")
    missing = [k for k in keys if not fields.get(k, "").strip()]
    if missing or not value.strip() and verb == "doc":
        refuse(done, what, "it has no " + (missing or ["file"])[0])
        return
    why = store.propose([head] + [k + ": " + " ".join(fields[k].split())
                                  for k in keys])
    if why:
        refuse(done, what, why)
        return
    done.proposed = done.proposed + 1
    done.lines.append(line + " (in facts/PROPOSED.md)")


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


def tally(run, trail):
    """count on each fact the steps of this leg it was handed, once the leg
    has ended: a count written while steps run would be a change to the
    place under them. a store that cannot be written is said, never raised."""
    store = getattr(run, "facts", None)
    if store is None or trail is None:
        return []
    try:
        return store.attached(entry.written or {}
                              for entry, _ in trail.closed)
    except (OSError, ValueError, KeyError) as e:
        print("facts: attached not counted: " + type(e).__name__ + ": "
              + str(e))
        return []
