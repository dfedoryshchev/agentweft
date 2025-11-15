import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


STATE = HERE / "state.json"
STATE_DIR = HERE / "state"


def _path(flow):
    STATE_DIR.mkdir(exist_ok=True)
    return STATE_DIR / (flow + ".json")


def load_state(flow):
    p = _path(flow)
    if p.exists():
        return json.loads(p.read_text())
    # anything left in the old single file, read it once
    if STATE.exists():
        return json.loads(STATE.read_text()).get(flow, {})
    return {}


def save_state(flow, entry):
    # one file per flow. the whole dict was being read, edited and written back
    # by each run, so whichever finished last wiped the other one out.
    p = _path(flow)
    fd, tmp = tempfile.mkstemp(dir=str(STATE_DIR), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(entry, f, indent=2)
    os.replace(tmp, p)
