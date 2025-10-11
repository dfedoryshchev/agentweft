import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


STATE = HERE / "state.json"


def load_state():
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_state(state):
    # write a temp file and swap it in. a half written state.json took me an
    # hour to work out the first time.
    fd, tmp = tempfile.mkstemp(dir=str(STATE.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE)
