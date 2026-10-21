"""the project's facts, written by the runner and by no step.

facts/ sits in the place beside decisions.md (`orchestrate/facts.py`), and
a fact tells the next step what this file's way is. a step with file tools
could write the fact that lets its own change through, the way it could
write a ruling, so facts get the same walls rulings have
(`guardrails/rulings.py`):

- the runner keeps its own account, runs/<id>/facts.json, outside the place:
  a sha256 of every entry there when the run started and of every entry it
  writes. between runs the store is the person's, and an entry written by
  hand counts.
- after each step the store is compared with what the runner last wrote; a
  step that added, edited or removed anything under facts/ fails like a gate
  and the store is put back. `rulings.Kept.check` runs this check with its
  own, so every place that checks decisions.md checks facts/ too.
- a `claude` step's Write and Edit tools are refused under facts/
  (`guardrails/shellwrite.py`).

and a fact the runner is asked to write is held to the record before
anything is written (`Store.add`): no secret in any field, a one-line claim
and a why, no `|`, a known kind and label, every scope in the place, evidence
the runner can check (a quoted line that is at that line, a command a gate
of this run ran with that exit code, a ruling on record), an anchor whose
hash the runner takes itself, at most `cap` new facts a run, and the same
claim on the same scope counted on the fact already there instead.
"""
import datetime
import hashlib
import json
import math
import re
import threading
from pathlib import Path

from agentweft.orchestrate import facts

FILE = "facts.json"
# new facts one run may write; more is a trail nobody reads
CAP = 3
EVIDENCE = re.compile(r"\bevidence:\s*(.*)$", re.S)
STAMPED = re.compile(r"^decisions\.md\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
RAN = re.compile(r"^`?(?P<cmd>.+?)`?\s+exit\s+(?P<code>-?\d+)\s*$")
SEEN = re.compile(r"(proposed|attached|honoured|contradicted) (\d+)")
COUNTERS = ("proposed", "attached", "honoured", "contradicted")
TOKEN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|sk_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
RANDOM = re.compile(r"[A-Za-z0-9+=_-]{32,}")
WORD = re.compile(r"[^\s`'\"(),;<>]+")
# the fields a proposal may carry, in the order an entry is written
FIELDS = ("scope", "kind", "label", "claim", "why", "source", "anchor",
          "check", "supersedes")


class Proposal(object):
    """a fact the runner is asked to write: `fields` by name, `scope` a list."""

    def __init__(self, fields):
        self.fields = dict(fields)
        scope = self.fields.get("scope") or []
        self.fields["scope"] = [scope] if isinstance(scope, str) else \
            list(scope)

    def get(self, key):
        value = self.fields.get(key)
        return "" if value is None else value

    def texts(self):
        """-> (field, text) for every field, one per scope."""
        for key in FIELDS:
            value = self.fields.get(key)
            for one in (value if isinstance(value, list) else [value]):
                if one:
                    yield key, str(one)


class Record(object):
    """what the run holds that evidence is checked against: the place, its
    start snapshot, the (command, exit code) of every gate it ran, and the
    stamps of the rulings on record."""

    def __init__(self, workdir, start=None, ran=(), stamps=()):
        self.workdir = Path(workdir)
        self.start = start
        self.ran = set((squash(c), int(n)) for c, n in ran)
        self.stamps = set(stamps)

    def holds(self, source):
        """-> "" when the source's evidence is on record, else why not."""
        m = EVIDENCE.search(source or "")
        said = m.group(1).strip() if m else ""
        if not said:
            return "it names no evidence"
        stamp = STAMPED.match(said)
        if stamp:
            if stamp.group(1) in self.stamps:
                return ""
            return "no ruling on record in decisions.md at " + stamp.group(1)
        from agentweft.runner import ruling

        quoted = ruling.CONFLICT.match(said) or ruling.FIRST_QUOTE.match(said)
        if quoted:
            rel, first, last, quote, cite = ruling.cite_of(quoted)
            if not quote:
                return cite + " quotes nothing"
            seen = [ruling.at_line(self.workdir, rel, first, last, at)[0]
                    for at in ([self.start, None] if self.start else [None])]
            seen = [s for s in seen if s is not None]
            if not seen:
                return cite + " is not lines of a file in the place"
            if any(quote in s for s in seen):
                return ""
            return '"' + quote + '" is not at ' + cite
        ran = RAN.match(said)
        if ran:
            cmd, code = squash(ran.group("cmd")), int(ran.group("code"))
            if (cmd, code) in self.ran:
                return ""
            return ("no gate in this run ran `" + cmd + "` to exit "
                    + str(code))
        return ("it names no quote, command or decisions.md stamp the runner"
                " can check")


def squash(text):
    return " ".join(str(text).split())


def entropy(text):
    counts = {}
    for c in text:
        counts[c] = counts.get(c, 0) + 1
    n = float(len(text))
    return -sum(k / n * math.log(k / n, 2) for k in counts.values())


def secret_in(text):
    """-> what in `text` looks like a secret, "" for nothing: a token of a
    known shape, a file that holds one by its name, a long random string."""
    from agentweft.guardrails import police
    from agentweft.runner.brief import CREDENTIAL

    if TOKEN.search(text):
        return "a token"
    for word in WORD.findall(text):
        word = word.rstrip(".:,!?")
        name = word.replace("\\", "/").rsplit("/", 1)[-1]
        if name and (CREDENTIAL.match(name) or police.secret(word)):
            return "a credential file"
    for run in RANDOM.findall(text):
        if re.search(r"[A-Z]", run) and re.search(r"[a-z]", run) \
                and re.search(r"\d", run) and entropy(run) >= 4.0:
            return "a long random string"
    return ""


def norm_claim(text):
    return " ".join(text.casefold().split()).rstrip(".")


def digest(fact):
    text = "\n".join(fact.lines())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def in_place(root, scope):
    """whether `scope` names something in the place."""
    if scope == facts.PROJECT:
        return True
    base = Path(root)
    if facts.is_glob(scope):
        cut = min(scope.find(c) for c in "*?[" if c in scope)
        top = scope[:cut].rsplit("/", 1)[0] if "/" in scope[:cut] else ""
        under = base / top if top else base
        if not under.is_dir():
            return False
        pattern = facts.glob_re(scope)
        return any(pattern.match(p.relative_to(base).as_posix())
                   for p in under.rglob("*") if p.is_file()
                   and facts.FOLDER not in p.relative_to(base).parts[:1])
    if scope.endswith("/"):
        return (base / scope).is_dir()
    return (base / scope).is_file()


class Store(object):
    """the runner's own record of the facts in one place, and the only way a
    fact is written there."""

    def __init__(self, workdir, cap=CAP):
        self.root = Path(workdir)
        self.cap = cap
        self.lock = threading.Lock()
        self.folder = None
        self.written = []
        self.refused = []
        self.new = 0
        # the facts this run has counted a proposal on: a run counts once
        self.counted = set()
        self.taken()

    def taken(self):
        """note the store as it is now as the runner's own."""
        self.data = self.now()
        self.found = [digest(f) for f in facts.read(self.root)]

    def now(self):
        """-> {path under the place: bytes} for every file under facts/."""
        base = facts.folder(self.root)
        if not base.is_dir():
            return {}
        out = {}
        for p in sorted(base.rglob("*")):
            if p.is_file():
                try:
                    out[p.relative_to(self.root).as_posix()] = p.read_bytes()
                except OSError:
                    continue
        return out

    def known(self):
        return set(self.found) | set(w["sha256"] for w in self.written)

    def read(self):
        """-> the entries the runner has on record, every status."""
        known = self.known()
        return [f for f in facts.read(self.root) if digest(f) in known]

    def heal(self, today=None):
        """`facts.heal` as the runner's own write, before any step."""
        with self.lock:
            made = facts.heal(self.root, today)
            if made:
                self.index()
            self.taken()
            self.save()
            return made

    def index(self):
        """render facts/INDEX.md from the entries as they are now."""
        path = facts.folder(self.root) / facts.INDEX
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(facts.index_lines(facts.read(self.root)))
                    + "\n")

    def check(self, step, how=""):
        """-> "" when facts/ is as the runner left it, else why `step` fails,
        with the store put back."""
        with self.lock:
            now = self.now()
            if now == self.data:
                return ""
            known = self.known()
            changed = sorted(p for p in set(now) | set(self.data)
                             if now.get(p) != self.data.get(p))
            there = facts.read(self.root)
            seen = set(digest(f) for f in there)
            added = [f.id for f in there if digest(f) not in known]
            held = set()
            for rel, data in self.data.items():
                _, was = facts.parse(data.decode("utf-8", "replace"))
                held.update(digest(f) for f in was)
            gone = len(held - seen)
            self.put_back()
        said = []
        if added:
            said.append("added or edited " + ", ".join(added))
        if gone:
            said.append("removed " + str(gone) + (" entry" if gone == 1
                                                  else " entries"))
        return (", ".join(changed) + (" was" if len(changed) == 1
                                      else " were")
                + " changed by " + step + how + "; facts come only from the"
                " runner. " + (", ".join(said) + ". " if said else "")
                + "it was put back, and the change counts for nothing")

    def put_back(self):
        for rel in self.now():
            if rel not in self.data:
                try:
                    (self.root / rel).unlink()
                except OSError:
                    pass
        for rel, data in self.data.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        base = facts.folder(self.root)
        if base.is_dir():
            for d in sorted((p for p in base.rglob("*") if p.is_dir()),
                            key=lambda p: -len(p.parts)):
                try:
                    d.rmdir()
                except OSError:
                    pass
            if not self.data:
                try:
                    base.rmdir()
                except OSError:
                    pass

    def refusal(self, p, record):
        """-> why proposal `p` is not written, "" when it may be."""
        for key, text in p.texts():
            what = secret_in(text)
            if what:
                return "it looks like a secret: " + what + " in " + key
        claim, why = p.get("claim").strip(), p.get("why").strip()
        if not claim:
            return "it has no claim"
        if "\n" in claim:
            return "the claim is more than one line"
        if not why:
            return "it has no why"
        for key, text in p.texts():
            if "|" in text:
                return key + " holds a |, which no taught format carries"
        kind = p.get("kind").strip()
        if kind not in facts.KINDS:
            return ("kind " + (kind or "(none)") + " is not one of "
                    + ", ".join(facts.KINDS))
        label = p.get("label").strip()
        if label not in facts.LABELS + ("", "none"):
            return ("label " + label + " is not one of "
                    + ", ".join(facts.LABELS + ("none",)))
        scopes = [facts.norm(s) for s in p.get("scope")]
        if not scopes:
            return "it names no scope"
        for s in scopes:
            if not in_place(self.root, s):
                return "the scope " + s + " is not in the place"
        held = record.holds(p.get("source"))
        if held:
            return "the evidence does not hold: " + held
        said = p.get("anchor").strip()
        if said and self.anchor_for(said) is None:
            return "the anchor " + said.split()[0] + " is not lines of the file"
        old = p.get("supersedes").strip()
        if old and not [f for f in self.read() if f.id == old
                        and f.status in (facts.LIVE, facts.STALE)]:
            return ("it supersedes " + old + ", which is not a live or stale"
                    " fact")
        return ""

    def anchor_for(self, said):
        m = re.match(r"^(.+):(\d+)-(\d+)\b", said.strip())
        if not m:
            return None
        return facts.anchored(self.root, m.group(1), int(m.group(2)),
                              int(m.group(3)))

    def add(self, p, record, today=None, origin=None):
        """-> (the fact written or counted, "") or (None, why it was
        refused). a refusal is kept on `refused` with its reason."""
        with self.lock:
            why = self.refusal(p, record)
            if not why:
                fact, why = self.written_from(p, today, origin)
                if fact is not None:
                    return fact, ""
            self.refused.append((p, why))
            return None, why

    def written_from(self, p, today, origin):
        scopes = [facts.norm(s) for s in p.get("scope")]
        claim = norm_claim(p.get("claim"))
        for f in self.read():
            if f.status == facts.LIVE and sorted(f.scopes) == sorted(scopes) \
                    and norm_claim(f.claim) == claim:
                if f.id not in self.counted:
                    self.counted.add(f.id)
                    self.count(f, "proposed")
                return f, ""
        if self.new >= self.cap:
            return None, ("per-run cap: " + str(self.cap) + " new facts are"
                          " already written this run")
        every = facts.read(self.root)
        n = max([int(f.id[2:]) for f in every] + [0]) + 1
        fact = facts.Fact("F-%04d" % n, facts.LIVE)
        for s in scopes:
            fact.fields.append(("scope", s))
        fact.fields.append(("kind", p.get("kind").strip()))
        label = p.get("label").strip()
        if label and label != "none":
            fact.fields.append(("label", label))
        for key in ("claim", "why", "source"):
            fact.fields.append((key, " ".join(p.get(key).split())))
        said = p.get("anchor").strip()
        if said:
            fact.fields.append(("anchor", str(self.anchor_for(said))))
        for key in ("check", "supersedes"):
            if p.get(key).strip():
                fact.fields.append((key, p.get(key).strip()))
        stamp = today or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        fact.fields.append(("written", stamp + " by runner"
                            + (" from " + origin if origin else "")))
        fact.fields.append(("seen", seen_line({"proposed": 1})))
        old = p.get("supersedes").strip()
        if old:
            self.status(old, facts.SUPERSEDED, "superseded",
                        stamp + " by " + fact.id)
        self.put(fact, facts.file_for(scopes[0]))
        self.new = self.new + 1
        self.counted.add(fact.id)
        return fact, ""

    def put(self, fact, rel):
        """write `fact` into facts/<rel>, as the runner's."""
        path = facts.folder(self.root) / rel
        head, found = (facts.parse(path.read_text(encoding="utf-8"), path)
                       if path.is_file() else (["# facts: " + rel[:-3]], []))
        found = [f for f in found if f.id != fact.id] + [fact]
        facts.write(path, head, found)
        self.mine(fact)

    def mine(self, fact):
        self.written.append({"id": fact.id, "status": fact.status,
                             "sha256": digest(fact)})
        self.index()
        self.data = self.now()
        self.save()

    def status(self, id, status, key, value):
        """set fact `id` to `status`, with `key: value` saying why, in its
        own file."""
        return self.change(id, lambda f: (setattr(f, "status", status),
                                          f.put(key, value)))

    def change(self, id, how):
        """apply `how` to fact `id` in its own file, as the runner's write;
        -> the fact, None when there is none."""
        for path in facts.files(self.root):
            head, found = facts.parse(path.read_text(encoding="utf-8"), path)
            for f in found:
                if f.id == id:
                    how(f)
                    facts.write(path, head, found)
                    self.mine(f)
                    return f
        return None

    def held(self, id):
        """-> fact `id` when the runner has it on record live or stale."""
        for f in self.read():
            if f.id == id and f.status in (facts.LIVE, facts.STALE):
                return f
        return None

    def reanchor(self, id, said, evidence, record, today=None):
        """-> "" once fact `id` is anchored on `said` again and live, else
        why not: the fact is not live or stale, the evidence that it still
        holds is not on record, or the lines are not there."""
        with self.lock:
            for key, text in (("anchor", said), ("evidence", evidence)):
                what = secret_in(text or "")
                if what:
                    return "it looks like a secret: " + what + " in " + key
            if self.held(id) is None:
                return id + " is not a live or stale fact"
            held = record.holds("evidence: " + (evidence or ""))
            if held:
                return "the evidence does not hold: " + held
            at = self.anchor_for(said or "")
            if at is None:
                return ("the anchor " + ((said or "").split() or ["(none)"])[0]
                        + " is not lines of the file")
            stamp = today or datetime.date.today().isoformat()

            def anchored(f):
                f.status = facts.LIVE
                f.put("anchor", str(at))
                f.drop("stale")
                f.put("healed", stamp + " anchored again by the retro")

            self.change(id, anchored)
            return ""

    def retire(self, id, why, today=None):
        """-> "" once fact `id` is retired, else why not."""
        with self.lock:
            why = " ".join((why or "").split())
            if not why:
                return "it has no why"
            what = secret_in(why)
            if what:
                return "it looks like a secret: " + what + " in why"
            if "|" in why:
                return "why holds a |, which no taught format carries"
            if self.held(id) is None:
                return id + " is not a live or stale fact"
            stamp = today or datetime.date.today().isoformat()
            self.status(id, facts.RETIRED, "retired",
                        stamp + " by the retro: " + why)
            return ""

    def propose(self, lines):
        """-> "" once `lines` are at the end of facts/PROPOSED.md, else why
        not. what is there is for a person; the runner applies none of it."""
        with self.lock:
            for text in lines:
                what = secret_in(text)
                if what:
                    return "it looks like a secret: " + what
            path = facts.folder(self.root) / facts.PROPOSED
            path.parent.mkdir(parents=True, exist_ok=True)
            head = [] if path.is_file() else [
                "# proposed", "", "guards and doc changes the retro proposed."
                " the runner applies none of them.", ""]
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(head + list(lines) + [""]) + "\n")
            self.data = self.now()
            self.save()
            return ""

    def count(self, fact, counter, n=1):
        """add `n` to one of the fact's `seen` counters, in its file."""
        said = dict((k, int(v)) for k, v in SEEN.findall(fact.get("seen")))
        if "proposed" not in said:
            said["proposed"] = 1
        said[counter] = said.get(counter, 0) + n
        fact.put("seen", seen_line(said))
        head, found = facts.parse(fact.file.read_text(encoding="utf-8"),
                                  fact.file)
        found = [fact if f.id == fact.id else f for f in found]
        facts.write(fact.file, head, found)
        self.mine(fact)

    def keep_in(self, folder):
        self.folder = Path(folder)
        self.save()

    def save(self):
        """write the account, once there is a store or a proposal to keep
        one of: a place with no facts/ leaves no file."""
        if self.folder is None or not (self.data or self.found or self.written
                                       or self.refused):
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        # a refusal keeps its scope and reason only: the claim may be the
        # secret it was refused for
        (self.folder / FILE).write_text(
            json.dumps({"found": self.found, "written": self.written,
                        "refused": [{"scope": p.get("scope"), "why": why}
                                    for p, why in self.refused]},
                       indent=2) + "\n", encoding="utf-8")


def seen_line(said):
    return ", ".join(k + " " + str(said.get(k, 0)) for k in COUNTERS)


def seen_of(fact):
    """-> {counter: n} from the fact's `seen` line, proposed 1 when unsaid."""
    said = dict((k, int(v)) for k, v in SEEN.findall(fact.get("seen")))
    said.setdefault("proposed", 1)
    return said


def cap_of(fm):
    """-> the flow's `facts_per_run`, CAP when it names none."""
    said = fm.get("facts_per_run") if hasattr(fm, "get") else None
    return CAP if said is None else int(said)
