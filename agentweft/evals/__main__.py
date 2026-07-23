import sys
import time

from agentweft.runner.config import config

from . import harness


def main():
    if len(sys.argv) < 2:
        print("usage: python -m agentweft.evals <flow>")
        return 1
    flow = sys.argv[1]
    spec = config(flow)
    cases = harness.cases_for(flow)
    if not cases:
        print("no cases under evals/" + flow + "/cases")
        return 1

    results = []
    for path in cases:
        case = harness.load_case(path)
        started = time.time()
        out, budget = harness.run_flow_for(flow, case)
        results.append((case["name"],
                        harness.score(spec, out, budget, time.time() - started)))
    print(harness.table(flow, results))
    if "--no-save" not in sys.argv:
        harness.save_scores(flow, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
