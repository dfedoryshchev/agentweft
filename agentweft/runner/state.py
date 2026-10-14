"""what a flow remembers between runs: the last one, per project and task.

it is kept under the runs root, one file per flow, repo and task, so two
projects run from one install never hand each other their last run, and two
runs at once in different places never write the same file.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


# where every flow's state was kept before it was per project. read, never
# written: an entry there for another place is somebody else's run
STATE = HERE / "state.json"
STATE_DIR = HERE / "state"
RUNS = HERE.parent / "runs"


def root_of(place):
    """-> the top of the repo `place` is in, or `place` when it is in none."""
    here = Path(place).resolve()
    for p in [here] + list(here.parents):
        if (p / ".git").exists():
            return p
    return here


def key(place, task=None):
    said = str(root_of(place)) + "\0" + (task or "")
    return hashlib.sha256(said.encode("utf-8")).hexdigest()[:16]


def _path(flow, place, task):
    return RUNS / ("last-run-" + flow + "-" + key(place, task) + ".json")


def _before(flow, place):
    old = {}
    p = STATE_DIR / (flow + ".json")
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
    elif STATE.exists():
        old = json.loads(STATE.read_text(encoding="utf-8")).get(flow, {})
    said = old.get("workdir")
    if not said or Path(said).resolve() != Path(place).resolve():
        return {}
    return old


def load_state(flow, place, task=None):
    """-> what the last run of `flow` on this repo and task left, {} when
    there was none."""
    p = _path(flow, place, task)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return _before(flow, place)


def save_state(flow, entry, place, task=None):
    p = _path(flow, place, task)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    os.replace(tmp, p)
