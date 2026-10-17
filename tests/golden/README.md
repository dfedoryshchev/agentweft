# golden runs

Each file here is what one shipped flow did on one path (pass, gate fail, redo), replayed by `tests/test_golden.py` with the cli answering from a script: the steps, the gates, the journal and index lines, the handoff, the files left behind and what it printed. Times, run ids, seconds and temp paths are taken out before the compare. `risky-edit` is not shipped: it is a test flow in `tests/flows/`, there to pin a preflight park against a ranking the replay hands it: `hot-plan` parks before the worker on a plan that names a hot file, `hot-park` parks after it on a worker that touched one the plan did not name.

A case with `legs` runs `main()` once per leg, each leg a minute after the one before, and `--resume` picks up the run the leg before left; its `exit`, `raised` and `printed` are one entry per leg. `outage-resume` parks on a usage-limit reply with no tokens in it (a refused go, not a call) and the resume runs the step that got no answer. `capped` is a test flow with `max_calls: 1`: `budget-resume` parks before the reviewer, the plain resume is refused at the cap, and the resume with `--max-calls 2` finishes. `chained-resume` is a resume of a resume: the last handoff carries the first leg's block and red proof, and each stop names the test it leaves red.

`suite-red` (fix-with-test, build-feature) is a change that turns its own test green and leaves another test in the suite red: the command gate fails it, sends the step back once, and the run stops on the second red suite.

`python -m pytest tests/test_golden.py --update-golden` rewrites them from what the code does now. A change that moves a golden path rewrites its golden in the same commit and says so; a new path adds its golden there too.
