"""the project's facts, written by the runner and by no step.

facts/ sits in the place beside decisions.md (`orchestrate/facts.py`), and
a fact tells the next step what this file's way is. a step with file tools
could write the fact that lets its own change through, the way it could
write a ruling, so facts get the same walls rulings have
(`guardrails/rulings.py`):

- the runner keeps its own account, runs/<id>/facts.json, outside the place:
  a sha256 of every entry there when the run started and of every entry it
  writes, and of every file outside facts/ it changes for the retro
  (`applied`), which a leg that carries the run on takes as the runner's.
  between runs the store is the person's, and an entry written by hand
  counts.
- after each step the store is compared with what the runner last wrote; a
  step that added, edited or removed anything under facts/ fails like a gate
  and the store is put back. `rulings.Kept.check` runs this check with its
  own, so every place that checks decisions.md checks facts/ too.
- a `claude` step's Write and Edit tools are refused under facts/
  (`guardrails/shellwrite.py`).
- two runs on one place share a Ledger of what each wrote, so neither
  takes the other's writes for a step's.

and a fact the runner is asked to write is held to the record before
anything is written (`Store.add`): no secret in any field, a one-line claim
and a why, no `|`, a known kind and label, no `gate-issue` that names an OS
error code (`WinError n`, `Errno n`: what the machine raised as the run went,
which a later run on a sound machine would be handed as the project's), no
convention or gate-issue that names the run's own shell or host, every
scope in the place, evidence
the runner can check (a quoted line that is at that line, its escapes read
(`quote_of`), a command a gate
of this run ran with that exit code, a ruling on record), an anchor whose
hash the runner takes itself, a check that reads only its scope and holds
on the place now, a convention that says every or never only with a check
a line against it breaks (`exits 1`), at most `cap` new facts a run, and
the same claim on the same scope counted on the fact already there instead.

a fact's check runs again after every step that changed a file in its scope
(`Store.conform`), and the end of the leg counts each step whose change held
it or broke it (`Store.held_to`).
"""
import base64
import contextlib
import datetime
import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path

from agentweft.orchestrate import facts

FILE = "facts.json"
# new facts one run may write; more is a trail nobody reads
CAP = 3
EVIDENCE = re.compile(r"\bevidence:\s*(.*)$", re.S)
STAMPED = re.compile(r"^decisions\.md\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")
RAN = re.compile(r"^`?(?P<cmd>.+?)`?\s+exit\s+(?P<code>-?\d+)\s*$")
CITE = re.compile(r'''^[`'"]?([^\s:`'"]+):(\d+)(?:-(\d+))?[`'"]?\s+"''')
ESCAPED = re.compile(r'\\(["\\])')
SEEN = re.compile(r"(proposed|attached|honoured|contradicted) (\d+)")
COUNTERS = ("proposed", "attached", "honoured", "contradicted")
GATE_ISSUE = "gate-issue"
OS_ERROR = re.compile(r"\[?\b(?:WinError|Errno) \d+\b")
# the kinds a later run takes as the project's rule
CONVENTION = "convention"
HOSTED = (CONVENTION, GATE_ISSUE)
# a claim about every place in its scope, which one matching line never shows
EVERY = re.compile(r"\b(?:every|each|all|always|never|none|nowhere)\b", re.I)
# the run's own shell and host, never the product's: a bare OS name or
# "shell" is left alone, since a product may support Windows or never start
# a shell
HOST = re.compile(
    r"\b(?:this|the run's|the runner's|the step's|the step) (?:machine|host"
    r"|box|computer|shell|terminal|windows|macos|mac|linux|os)\b"
    r"|\b(?:antivirus|WinError \d+|Errno \d+)\b", re.I)
# shells and toolchains a product may use or ship as well: a gate-issue that
# names one is the run's host, a convention only with HOST beside it
SHELLS = re.compile(r"\b(?:git bash|powershell|cmd\.exe|msys2?|mingw(?:64)?"
                    r"|cygwin|python -c|here-?docs?)\b", re.I)
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
BREACH = re.compile(r"^\W*CONVENTION:\s*(F-\d+)\b", re.M)
REDO = re.compile(r"^\W*VERDICT:\s*redo\b", re.M | re.I)


def breaches(line, folder):
    """-> the ids of the facts a pass sent back on its own `VERDICT: redo`
    names on its `CONVENTION:` lines, each once, read from its answer under
    `folder`; [] for any other pass or an answer that cannot be read."""
    if folder is None or (line or {}).get("outcome") != "redo" \
            or not line.get("file"):
        return []
    try:
        said = (Path(folder) / line["file"]).read_text(encoding="utf-8")
    except OSError:
        return []
    if not REDO.search(said):
        return []
    out = []
    for id in BREACH.findall(said):
        if id not in out:
            out.append(id)
    return out


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

        quoted = quote_of(said)
        if quoted:
            rel, first, last, cite, body = quoted
            if body is None:
                return ("the quote of " + cite + " stops at a \" inside it,"
                        " so it is cut short")
            quote = ruling.flat(body)
            if not quote:
                return cite + " quotes nothing"
            seen = [ruling.at_line(self.workdir, rel, first, last, at)[0]
                    for at in ([self.start, None] if self.start else [None])]
            seen = [s for s in seen if s is not None]
            if not seen:
                return cite + " is not lines of a file in the place"
            if any(ruling.flat(q) in s for q in read_as(body) for s in seen):
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


def quote_of(said):
    """-> None when evidence `said` is not `<file>:<line> "<quote>"`, else
    (file, first line, last line, the cite, the quote as written). the quote
    runs to the last `"` of the evidence, inner quotes and all; one followed
    by more words ends at its first `"` not written `\\"`, and is None when
    another `"` comes after that one: it was cut at a quote of its own."""
    m = CITE.match(said)
    if not m:
        return None
    rel, first = m.group(1), int(m.group(2))
    last = int(m.group(3) or first)
    cite = rel + ":" + str(first) + ("-" + str(last) if last != first else "")
    rest = said[m.end():].rstrip()
    if rest.endswith('"'):
        return rel, first, last, cite, rest[:-1]
    shut = closing(rest)
    if shut < 0:
        return None
    if closing(rest, shut + 1) >= 0:
        return rel, first, last, cite, None
    return rel, first, last, cite, rest[:shut]


def closing(text, at=0):
    """-> where the first `"` from `at` on that is not written `\\"` is in
    `text`, or -1."""
    while at < len(text):
        if text[at] == "\\":
            at += 2
            continue
        if text[at] == '"':
            return at
        at += 1
    return -1


def read_as(body):
    """-> the ways a quote can be read: as written, with `\\"` read as `"`,
    and with `\\\\` read as `\\` too. each is held to the file, so reading
    one that is not there admits nothing."""
    quotes = body.replace('\\"', '"')
    out = [body, quotes, ESCAPED.sub(lambda m: m.group(1), body)]
    return [q for n, q in enumerate(out) if q not in out[:n]]


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
                   and not facts.is_store(p.relative_to(base).as_posix()))
    if scope.endswith("/"):
        return (base / scope).is_dir()
    return (base / scope).is_file()


LEDGERS = "facts-ledger"
# how long a write or a check waits for another run's to end before it goes
# on alone
WAIT = 30.0
_HELD = {}
_HELD_LOCK = threading.Lock()


class Ledger(object):
    """what every run on one place last wrote to each store file, kept in the
    runner's own folder: a second run on the place reads it, so its check
    takes the first run's writes for the runner's and not a step's, and
    neither puts back the other's facts. writes and checks on the place take
    turns under one lock, so two runs never pick the same id."""

    def __init__(self, own, root):
        key = hashlib.sha256(os.path.normcase(os.path.realpath(str(root)))
                             .encode("utf-8")).hexdigest()[:16]
        self.path = Path(own) / (LEDGERS + "-" + key + ".json")
        self.gate = self.path.with_suffix(".lock")

    @contextlib.contextmanager
    def held(self):
        """one writer or checker on the place at a time, across runs."""
        with _HELD_LOCK:
            entry = _HELD.setdefault(str(self.gate),
                                     [threading.RLock(), 0, None])
        with entry[0]:
            if entry[1] == 0:
                entry[2] = take(self.gate)
            entry[1] = entry[1] + 1
            try:
                yield
            finally:
                entry[1] = entry[1] - 1
                if entry[1] == 0 and entry[2] is not None:
                    give(entry[2])
                    entry[2] = None

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def record(self, root, rels):
        """note the bytes of each of `rels` as they are now as the runner's
        latest write of it."""
        data = self.read()
        at = time.time()
        for rel in rels:
            try:
                raw = (Path(root) / rel).read_bytes()
            except OSError:
                raw = None
            data[rel] = {"at": at, "bytes": None if raw is None
                         else base64.b64encode(raw).decode("ascii")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_suffix(".part")
        part.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(part), str(self.path))


def take(gate):
    """-> the open file `gate` once this process holds its lock, None when
    it could not within WAIT."""
    gate.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(str(gate), "a+b")
    except OSError:
        return None
    until = time.time() + WAIT
    while True:
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.time() > until:
                fh.close()
                return None
            time.sleep(0.05)


def give(fh):
    try:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    fh.close()


class Store(object):
    """the runner's own record of the facts in one place, and the only way a
    fact is written there. `off` is a flow's `lane: off`: the run reads,
    heals and writes none of them, and a step is still held to leaving the
    store as it found it. with `own`, the runner's folder, it keeps a Ledger
    there that other runs on the same place share."""

    def __init__(self, workdir, cap=CAP, off=False, own=None):
        self.root = Path(workdir)
        self.cap = cap
        self.off = off
        # the runner's own folder, which no check reads
        self.own = own
        self.ledger = Ledger(own, self.root) if own is not None else None
        self.lock = threading.Lock()
        self.folder = None
        self.written = []
        self.refused = []
        self.new = 0
        # the entries another run on the place wrote, taken from the ledger
        self.adopted = set()
        # the facts this run has counted a proposal on: a run counts once
        self.counted = set()
        # every store file the runner wrote, in order, and the files outside
        # facts/ it changed for the retro (`runner/upkeep.py`)
        self.touched = []
        self.applied = []
        self.taken()
        self.watch()

    def shared(self, force=False):
        """the place's turn, when another run may share it: taken once the
        place has a store, or with `force` for a write that may start one.
        a place with no facts leaves nothing in the runner's folder."""
        if self.ledger is None or not (force or self.data
                                       or facts.folder(self.root).is_dir()):
            return contextlib.nullcontext()
        return self.ledger.held()

    def taken(self):
        """note the store as it is now as the runner's own."""
        self.data = self.now()
        self.at = time.time()
        self.found = [digest(f) for f in facts.read(self.root)]

    def wrote(self, rels):
        """note `rels`, store files the runner has just written, as its own
        and in the ledger."""
        rels = sorted(set(rels))
        self.touched.extend(r for r in rels if r not in self.touched)
        for rel in rels:
            try:
                self.data[rel] = (self.root / rel).read_bytes()
            except OSError:
                self.data.pop(rel, None)
        if self.ledger is not None and rels:
            self.ledger.record(self.root, rels)
        self.save()

    def expected(self):
        """-> the store as the runner left it: this run's writes, and every
        file another run on the place wrote since this one took it."""
        out = dict(self.data)
        if self.ledger is None:
            return out
        for rel, was in self.ledger.read().items():
            if not isinstance(was, dict) or was.get("at", 0) <= self.at:
                continue
            if was.get("bytes") is None:
                out.pop(rel, None)
            else:
                out[rel] = base64.b64decode(was["bytes"])
        return out

    def rel(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def now(self):
        """-> {path under the place: bytes} for every one of the store's
        files (`facts.is_store`)."""
        base = facts.folder(self.root)
        if not base.is_dir():
            return {}
        out = {}
        for p in sorted(base.rglob("*")):
            if p.is_file() and facts.is_store(
                    p.relative_to(self.root).as_posix()):
                try:
                    out[p.relative_to(self.root).as_posix()] = p.read_bytes()
                except OSError:
                    continue
        return out

    def known(self):
        return set(self.found) | set(w["sha256"] for w in self.written) \
            | self.adopted

    def read(self):
        """-> the entries the runner has on record, every status; none when
        the lane is off."""
        if self.off:
            return []
        known = self.known()
        return [f for f in facts.read(self.root) if digest(f) in known]

    def heal(self, today=None):
        """`facts.heal` as the runner's own write, before any step."""
        if self.off:
            return []
        with self.lock, self.shared():
            before = self.now()
            made = facts.heal(self.root, today)
            if made:
                self.index()
            self.taken()
            after = self.data
            if self.ledger is not None:
                rels = [r for r in set(before) | set(after)
                        if before.get(r) != after.get(r)]
                if rels:
                    self.ledger.record(self.root, rels)
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
        with the store put back. what another run on the place wrote since
        is the runner's too, and is taken as this run's own."""
        with self.lock:
            if self.now() == self.data and not self.data:
                return ""
        with self.lock, self.shared():
            now = self.now()
            if now == self.data:
                return ""
            ours = self.expected()
            if now == ours:
                self.adopt(ours)
                return ""
            self.adopt(ours)
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

    def adopt(self, store):
        """take `store`, {path: bytes}, as this run's own from now on."""
        for raw in store.values():
            _, found = facts.parse(raw.decode("utf-8", "replace"))
            self.adopted.update(digest(f) for f in found)
        self.data = dict(store)
        self.at = time.time()

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
        if kind == GATE_ISSUE and any(OS_ERROR.search(text)
                                      for _, text in p.texts()):
            return ("a gate-issue that names an OS error code is the"
                    " machine's state as the run went, not the project's: a"
                    " later run on a sound machine would be handed it")
        if kind in HOSTED:
            words = (HOST, SHELLS) if kind == GATE_ISSUE else (HOST,)
            host = next((m.group(0) for m in (w.search(p.get(key))
                                              for w in words
                                              for key in ("claim", "why"))
                         if m), "")
            if host:
                return ("a " + kind + " that names the run's own machine or"
                        " shell (" + host + ") is how this host behaved, not"
                        " the project's way: a later run on another machine"
                        " would be handed it as a rule of the project")
        label = p.get("label").strip()
        if label not in facts.LABELS + ("", "none"):
            return ("label " + label + " is not one of "
                    + ", ".join(facts.LABELS + ("none",)))
        scopes = [facts.norm(s) for s in p.get("scope")]
        if not scopes:
            return "it names no scope"
        for s in scopes:
            if facts.escapes(self.root, s):
                return "the scope " + s + " is outside the place"
            if not in_place(self.root, s):
                return "the scope " + s + " is not in the place"
        held = record.holds(p.get("source"))
        if held:
            return "the evidence does not hold: " + held
        said = p.get("anchor").strip()
        if said and self.anchor_out(said):
            return "the anchor " + self.anchor_out(said) + " is outside the" \
                " place"
        if said and self.anchor_for(said) is None:
            return "the anchor " + said.split()[0] + " is not lines of the file"
        said = p.get("check").strip()
        if said:
            why = self.check_refusal(said, scopes)
            if why:
                return why
        why = every_refusal(p, said)
        if why:
            return why
        old = p.get("supersedes").strip()
        if old and not [f for f in self.read() if f.id == old
                        and f.status in (facts.LIVE, facts.STALE)]:
            return ("it supersedes " + old + ", which is not a live or stale"
                    " fact")
        return ""

    def check_refusal(self, said, scopes):
        """-> why a fact with check `said` is not written: the check cannot
        run, reads a file outside the fact's scopes, or does not hold on the
        place as it is now."""
        check, why = facts.parse_check(said)
        if check is None:
            return "the check cannot run: " + why
        why = beyond(check, scopes)
        if why:
            return why
        held, why = facts.run_check(self.root, said, self.own)
        if held is None:
            return "the check cannot run: " + why[len("could not run: "):]
        if not held:
            return "the check does not hold on the tree as it is: " + why
        return ""

    def conform(self, again=False):
        """-> a line per live fact with a check whose scope changed since it
        was last looked at, with what the check said: held, broken or could
        not run. `again` keeps a broken one's scope as it was, so the next
        step is held to it too until it holds."""
        if self.off:
            return []
        out = []
        with self.lock, self.shared():
            for f in self.read():
                said = f.get("check").strip()
                if f.status != facts.LIVE or not said:
                    continue
                now = facts.scope_digest(self.root, f.scopes, self.own)
                was = self.watched.setdefault(f.id, now)
                if was == now and f.id not in self.pending:
                    continue
                held, why = self.run(f)
                result = facts.HELD if held else facts.UNRUN \
                    if held is None else facts.BROKEN
                if result == facts.BROKEN and again:
                    self.pending.add(f.id)
                else:
                    self.pending.discard(f.id)
                    self.watched[f.id] = now
                out.append({"fact": f.id, "scope": f.scopes,
                            "claim": f.claim, "check": said,
                            "result": result, "said": why})
        return out

    def run(self, f):
        """-> what fact `f`'s check says on the place now, as `run_check`
        does; a check that reads outside the fact's scope cannot run, here
        as when the fact is written."""
        check, _ = facts.parse_check(f.get("check"))
        why = beyond(check, f.scopes) if check is not None else ""
        if why:
            return None, "could not run: " + why
        return facts.run_check(self.root, f.get("check").strip(), self.own)

    def hold_broken(self):
        """hold every live fact whose check is broken on the place now as
        broken until a step makes it hold: a leg that picks up a run with
        `conformance: fail` carries on the break the leg before it left."""
        if self.off:
            return
        with self.lock, self.shared():
            for f in self.read():
                if f.status == facts.LIVE and f.get("check").strip() \
                        and self.run(f)[0] is False:
                    self.pending.add(f.id)

    def watch(self):
        """note the scope of every live fact with a check as it is now."""
        self.watched, self.pending = {}, set()
        if self.off:
            return
        for f in self.read():
            if f.status == facts.LIVE and f.get("check").strip():
                self.watched[f.id] = facts.scope_digest(self.root, f.scopes,
                                                        self.own)

    def held_to(self, lines, folder=None):
        """add one to a fact's `honoured` for each check it held after a
        step of `lines`, the run's steps.jsonl lines, and to `contradicted`
        for each it was broken, and for each pass sent back with a
        `CONVENTION:` line naming it, read from the pass's answer under
        `folder`; -> the ids counted. a check that could not run counts for
        neither."""
        tally = {}
        for line in lines:
            for c in (line or {}).get("conformance") or []:
                key = {facts.HELD: "honoured",
                       facts.BROKEN: "contradicted"}.get(c.get("result"))
                if key:
                    tally.setdefault(c.get("fact"), {}).setdefault(key, 0)
                    tally[c.get("fact")][key] += 1
            for id in breaches(line, folder):
                tally.setdefault(id, {}).setdefault("contradicted", 0)
                tally[id]["contradicted"] += 1
        out = []
        with self.shared():
            for fact in self.read() if tally else []:
                for key, n in sorted((tally.get(fact.id) or {}).items()):
                    self.count(fact, key, n)
                    if fact.id not in out:
                        out.append(fact.id)
        return out

    def anchor_out(self, said):
        """-> the path of anchor `said` when it leaves the place, else ""."""
        m = re.match(r"^(.+):(\d+)-(\d+)\b", said.strip())
        if m and facts.escapes(self.root, m.group(1)):
            return m.group(1)
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
        with self.lock, self.shared(force=True):
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
        if facts.escapes(facts.folder(self.root), rel):
            raise ValueError(rel + " is not a file under facts/")
        head, found = (facts.parse(path.read_text(encoding="utf-8"), path)
                       if path.is_file() else (["# facts: " + rel[:-3]], []))
        found = [f for f in found if f.id != fact.id] + [fact]
        facts.write(path, head, found)
        self.mine(fact, path)

    def mine(self, fact, path):
        """note `fact`, just written into `path`, as the runner's."""
        self.written.append({"id": fact.id, "status": fact.status,
                             "sha256": digest(fact)})
        self.index()
        self.wrote([self.rel(path),
                    facts.FOLDER + "/" + facts.INDEX])

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
                    self.mine(f, path)
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
        with self.lock, self.shared():
            for key, text in (("anchor", said), ("evidence", evidence)):
                what = secret_in(text or "")
                if what:
                    return "it looks like a secret: " + what + " in " + key
            if self.held(id) is None:
                return id + " is not a live or stale fact"
            if self.anchor_out(said or ""):
                return ("the anchor " + self.anchor_out(said)
                        + " is outside the place")
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
        with self.lock, self.shared():
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
        not. what is there is for a person: the retro's guards and doc
        changes that failed a check, and the guards its ladder owes."""
        with self.lock, self.shared(force=True):
            for text in lines:
                what = secret_in(text)
                if what:
                    return "it looks like a secret: " + what
            path = facts.folder(self.root) / facts.PROPOSED
            path.parent.mkdir(parents=True, exist_ok=True)
            head = [] if path.is_file() else [
                "# proposed", "", "the retro's guards and doc changes that"
                " failed a check, each with why, and the guards a recurring"
                " fact is owed. the runner made none of them.", ""]
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(head + list(lines) + [""]) + "\n")
            self.wrote([self.rel(path)])
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
        self.mine(fact, fact.file)

    def attached(self, lines):
        """add one to a fact's `attached` for each line of `lines`, the
        run's steps.jsonl lines, that says it was handed the fact; -> the
        ids counted."""
        tally = {}
        for line in lines:
            for id in (line or {}).get("facts_attached") or []:
                tally[id] = tally.get(id, 0) + 1
        out = []
        with self.shared():
            for fact in self.read() if tally else []:
                if fact.id in tally and fact.id not in out:
                    self.count(fact, "attached", tally[fact.id])
                    out.append(fact.id)
        return out

    def applied_write(self, rel, kind, because):
        """note `rel`, a file outside facts/ the runner just changed for the
        retro, as the runner's write: its bytes now, what it is and why."""
        data = (self.root / rel).read_bytes()
        self.applied.append({"path": rel, "kind": kind,
                             "sha256": hashlib.sha256(data).hexdigest(),
                             "because": because})
        self.save()

    def keep_in(self, folder):
        self.folder = Path(folder)
        self.save()

    def save(self):
        """write the account, once there is a store or a proposal to keep
        one of: a place with no facts/ leaves no file."""
        if self.folder is None or not (self.data or self.found or self.written
                                       or self.refused or self.applied):
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        # a refusal keeps its scope and reason only: the claim may be the
        # secret it was refused for
        account = {"found": self.found, "written": self.written,
                   "refused": [{"scope": p.get("scope"), "why": why}
                               for p, why in self.refused]}
        if self.applied:
            account["applied"] = self.applied
        (self.folder / FILE).write_text(json.dumps(account, indent=2) + "\n",
                                        encoding="utf-8")


def applied_in(folders):
    """-> {path from the place: sha256} of every file outside facts/ the
    runner changed for a retro in the run folders `folders`, the last write
    of each: a step after it that leaves those bytes changed nothing."""
    out = {}
    for folder in folders:
        try:
            data = json.loads((Path(folder) / FILE).read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for w in (data.get("applied") or []) if isinstance(data, dict) \
                else []:
            if isinstance(w, dict) and w.get("path") and w.get("sha256"):
                out[w["path"]] = w["sha256"]
    return out


def every_of(p):
    """-> the word a convention's claim says every or never with, "" for
    any other fact."""
    if p.get("kind").strip() != CONVENTION:
        return ""
    m = EVERY.search(p.get("claim"))
    return m.group(0).lower() if m else ""


def every_refusal(p, said):
    """-> why a convention that says every or never is not written with
    check `said`, "" when it may be: it needs a check, and one that a line
    against the claim breaks."""
    word = every_of(p)
    if not word:
        return ""
    head = ("a convention that says " + word + " is kept only with a check"
            " that holds on the tree")
    if not said:
        return head + ", and it has none"
    check, _ = facts.parse_check(said)
    if check is not None and check.want != 1:
        return (head + ": an exits " + str(check.want) + " grep holds by one"
                " line, never by every one; it needs a pattern no line may"
                " match, exits 1")
    return ""


def beyond(check, scopes):
    """-> why a parsed `check` reads a path outside `scopes`, "" when it
    reads only inside them."""
    for path in check.paths:
        inside = [s for s in scopes if s == facts.PROJECT
                  or facts.rank(s, path) is not None
                  or s.endswith("/") and path.rstrip("/") + "/" == s]
        if not inside:
            return ("the check reads " + path + ", which is not in the"
                    " fact's scope")
    return ""


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


def lane_off(fm):
    """whether the flow says `lane: off`, which yaml may read as false."""
    said = fm.get("lane") if hasattr(fm, "get") else None
    return said is False or said == "off"
