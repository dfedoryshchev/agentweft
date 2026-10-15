"""what a run is, written beside it, so the run can be picked up from itself.

`runs/<run id>/manifest.json` is written when a run starts, after every step
that passes, and when it stops or finishes. `--resume <run id>` reads the one
in that folder. it used to read the journal, which is one file for every run
of every flow: its newest line for the flow was taken as the stop of whichever
run was named, so with two parked runs the older one was picked up at the
newer one's step, and a finished run after them made the resume start the
whole flow again.

it holds:

- every step's state - passed, parked, failed, redo or not run - the run whose
  folder has what the step produced last, and a digest of that
- what the run has spent, so a resumed run starts there and not at nothing
- a digest of every file in the flow folder, so an edited flow is named
- HEAD and the files git calls changed in the place, a digest each
- the task, the models chosen, the place, and the run the task started as

a fanned-out step writes each task to `tasks.jsonl` as it finishes, so a step
that died part way is picked up with only the tasks it had not done.
"""
import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

FILE = "manifest.json"
TASKS = "tasks.jsonl"

PASSED = "passed"
PARKED = "parked"
FAILED = "failed"
REDO = "redo"
NOT_RUN = "not run"

RUNNING = "running"
STOPPED = "stopped"
FINISHED = "finished"

DONE = (PASSED, PARKED)

_writing = threading.Lock()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def of_text(text):
    return None if text is None else sha(text.encode("utf-8"))


def of_file(path):
    try:
        return sha(Path(path).read_bytes())
    except OSError:
        return None


def flow_digest(folder):
    """-> (one digest for the flow folder, {file: digest}).

    the line endings are taken out first: the same flow checked out with CRLF
    is the same flow.
    """
    files = {}
    root = Path(folder)
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        files[p.relative_to(root).as_posix()] = sha(
            p.read_bytes().replace(b"\r\n", b"\n"))
    whole = sha("\n".join(k + " " + v for k, v in sorted(files.items()))
                .encode("utf-8"))
    return whole, files


def changed(before, now):
    """-> the names whose digest differs between two {name: digest}."""
    before, now = before or {}, now or {}
    return sorted(k for k in set(before) | set(now)
                  if before.get(k) != now.get(k))


def _git(place, *args):
    try:
        r = subprocess.run(["git", "-C", str(place)] + list(args),
                           capture_output=True, encoding="utf-8",
                           errors="replace")
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def tree(place, own=None):
    """-> {"head": the commit or None, "dirty": {path: digest}} of the place.

    a place git does not know has neither. `own` is the runs folder, left out
    when it is inside the place: every step writes there.
    """
    here = Path(place).resolve()
    if not any((p / ".git").exists() for p in [here] + list(here.parents)):
        return {"head": None, "dirty": {}}
    top = _git(place, "rev-parse", "--show-toplevel")
    if top is None:
        return {"head": None, "dirty": {}}
    top = Path(top.strip())
    head = _git(place, "rev-parse", "--verify", "-q", "HEAD")
    skip = []
    if own is not None:
        try:
            rel = Path(own).resolve().relative_to(Path(place).resolve())
            skip = [":(exclude,glob)" + rel.as_posix() + "/**"]
        except ValueError:
            pass
    out = _git(place, "status", "--porcelain", "-z", "--", ".", *skip) or ""
    dirty = {}
    fields = iter(out.split("\0"))
    for entry in fields:
        if not entry:
            continue
        code, rel = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            next(fields, None)
        dirty[rel] = of_file(top / rel)
    return {"head": head.strip() if head else None, "dirty": dirty}


def moved(before, now):
    """-> what is different in the place between two `tree`s, one line each."""
    out = []
    if (before or {}).get("head") != now.get("head"):
        out.append("HEAD " + str((before or {}).get("head"))[:12] + " -> "
                   + str(now.get("head"))[:12])
    for rel in changed((before or {}).get("dirty"), now.get("dirty")):
        out.append(rel)
    return out


class Manifest(object):
    """one run's manifest.json, read and written whole."""

    def __init__(self, folder, data):
        self.folder = Path(folder)
        self.data = data

    @classmethod
    def new(cls, folder, run, flow, name, order, flow_files, task=None,
            models=None, workdir="", origin=None, resumes=None):
        whole, files = flow_files
        return cls(folder, {
            "run": run, "flow": flow, "name": name, "state": RUNNING,
            "origin": origin or run, "resumes": resumes, "task": task,
            "models": dict(models or {}), "workdir": str(workdir),
            "flow_digest": whole, "flow_files": files, "tree": None,
            "steps": [{"step": s, "state": NOT_RUN, "in": None,
                       "digest": None} for s in order],
            "stopped": None, "spend": {}})

    def carried(self, folder, run, order, flow_files, workdir=""):
        """-> the manifest of the run that picks this one up.

        a parked step was let through by the person who carried on, so it is
        passed from here.
        """
        out = Manifest.new(folder, run, self.data["flow"], self.data["name"],
                           order, flow_files, task=self.task,
                           models=self.data.get("models"),
                           workdir=workdir or self.data.get("workdir", ""),
                           origin=self.origin, resumes=self.data["run"])
        for s in out.data["steps"]:
            old = self.step(s["step"])
            if old is not None:
                s.update(old)
                if s["state"] == PARKED:
                    s["state"] = PASSED
        out.data["spend"] = dict(self.spend)
        return out

    @property
    def run(self):
        return self.data["run"]

    @property
    def state(self):
        return self.data.get("state")

    @property
    def origin(self):
        return self.data.get("origin") or self.data["run"]

    @property
    def resumes(self):
        return self.data.get("resumes")

    @property
    def task(self):
        return self.data.get("task")

    @property
    def spend(self):
        return self.data.get("spend") or {}

    def step(self, name):
        for s in self.data["steps"]:
            if s["step"] == name:
                return s
        return None

    def mark(self, name, state, run=None, output=None):
        s = self.step(name)
        if s is None:
            s = {"step": name}
            self.data["steps"].append(s)
        s.update({"state": state, "in": run, "digest": of_text(output)})

    def start_at(self, order):
        """-> the first step in `order` with nothing passed for it, or None."""
        for name in order:
            s = self.step(name)
            if s is None or s["state"] not in DONE:
                return name
        return None

    def stop(self, step, cause, why, place, own=None):
        self.data["state"] = STOPPED
        self.data["stopped"] = {"step": step, "cause": cause, "why": why}
        self.data["tree"] = tree(place, own)

    def finish(self, place, own=None):
        self.data["state"] = FINISHED
        self.data["stopped"] = None
        self.data["tree"] = tree(place, own)

    def save(self, budget=None):
        if budget is not None:
            self.data["spend"] = budget.saved()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / FILE
        tmp = path.with_name(FILE + ".tmp")
        tmp.write_bytes((json.dumps(self.data, indent=2, ensure_ascii=False)
                         + "\n").encode("utf-8"))
        os.replace(str(tmp), str(path))
        return path


def load(folder):
    """-> the Manifest in a run folder, or None for a run that has none."""
    path = Path(folder) / FILE
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return Manifest(folder, data)


def legs(folder):
    """-> (the run folders of every leg up to `folder`, first leg first; the
    run id of an earlier leg whose folder is gone, or None).

    a leg names the one it picked up in `resumes`; one written before that
    link names only the run the task started as, in `origin`.
    """
    folder = Path(folder)
    out = [folder]
    seen = set([folder.name])
    m = load(folder)
    while m is not None:
        back = m.resumes or (m.origin if m.origin != m.run else None)
        if not back or back in seen:
            break
        seen.add(back)
        m = load(folder.parent / back)
        if m is None:
            return out[::-1], back
        out.append(folder.parent / back)
    return out[::-1], None


def task_done(folder, step, task, line, handoff):
    """one task of a fanned-out step, written down the moment it finished."""
    row = {"step": step, "task": task, "line": line, "output": handoff.output,
           "verdict": handoff.verdict, "asked": handoff.meta.get("asked")}
    with _writing:
        Path(folder).mkdir(parents=True, exist_ok=True)
        with open(Path(folder) / TASKS, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tasks_done(folder, step):
    """-> {(task, line): row} for every task of `step` the run finished. a
    task is matched on its line too: a plan edited since then is new work."""
    path = Path(folder) / TASKS
    if not path.exists():
        return {}
    out = {}
    for text in path.read_text(encoding="utf-8").split("\n"):
        try:
            row = json.loads(text)
        except ValueError:
            continue
        if row.get("step") == step and row.get("output"):
            out[(row["task"], row["line"])] = row
    return out
