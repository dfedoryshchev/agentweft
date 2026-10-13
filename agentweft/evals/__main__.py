import sys
import time

from agentweft.runner.config import config

from . import harness, recording


def main():
    if len(sys.argv) < 2:
        print("usage: python -m agentweft.evals <flow> [--case <name>]"
              " [--record] [--no-save]")
        return 1
    flow = sys.argv[1]
    spec = config(flow)
    cases = harness.cases_for(flow)
    if not cases:
        print("no cases under evals/" + flow + "/cases")
        return 1
    if "--case" in sys.argv:
        i = sys.argv.index("--case")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        picked = [p for p in cases if p.name == name]
        if not picked:
            print("no case called " + name + " under evals/" + flow
                  + "/cases. there is: " + ", ".join(p.name for p in cases))
            return 1
        cases = picked

    record = "--record" in sys.argv
    results = []
    unmatched = []
    for path in cases:
        case = harness.load_case(path)
        started = time.time()
        out, budget, stopped = harness.run_flow_for(flow, case, record=record)
        if stopped.startswith(recording.PREFIX):
            unmatched.append(case["name"])
        scored = harness.score(spec, out, budget, stopped,
                               time.time() - started)
        scored["replayed"] = bool(case["recording"]) and not record
        results.append((case["name"], scored))
    print(harness.table(flow, results))
    if unmatched:
        print("")
        print(", ".join(unmatched) + ": the recording does not match this run,"
              " so these scores are not saved. python -m agentweft.evals "
              + flow + " --record makes a new one")
        return 1
    if "--no-save" not in sys.argv:
        harness.save_scores(flow, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
