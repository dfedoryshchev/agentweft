# golden runs

Each file here is what one shipped flow did on one path (pass, gate fail, redo), replayed by `tests/test_golden.py` with the cli answering from a script: the steps, the gates, the journal and index lines, the handoff, the files left behind and what it printed. Times, run ids, seconds and temp paths are taken out before the compare. `risky-edit` is not shipped: it is a test flow in `tests/flows/`, there to pin a preflight park against a ranking the replay hands it.

`python -m pytest tests/test_golden.py --update-golden` rewrites them from what the code does now. A change that moves a golden path rewrites its golden in the same commit and says so; a new path adds its golden there too.
