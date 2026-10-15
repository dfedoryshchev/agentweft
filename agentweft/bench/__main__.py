import datetime
import json
import sys
from pathlib import Path

from . import runner, scorer

USAGE = ("usage: python -m agentweft.bench <set> [--k <n>] [--flow <flow>]"
         " [--out <file>] [--live]")
FAKE = "fake"


def valued(argv, flag):
    if flag not in argv:
        return None
    i = argv.index(flag)
    if len(argv) <= i + 1 or argv[i + 1].startswith("--"):
        raise ValueError(flag + " needs a value")
    return argv[i + 1]


def main(argv=None):
    from agentweft.runner import state
    from agentweft.runner.config import config

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        print(USAGE)
        return 1
    folder = Path(argv[0])
    if not folder.is_dir():
        print(str(folder) + ": no such folder")
        return 1
    try:
        k = valued(argv, "--k")
        flow = valued(argv, "--flow")
        out = valued(argv, "--out")
    except ValueError as e:
        print(str(e))
        return 1
    conf, tasks, problems = runner.load(folder)
    if problems:
        print("the set is not scored, nothing ran:")
        for p in problems:
            print("  " + p)
        return 1
    flow = flow or conf.get("flow")
    if not flow:
        print("no flow: name one in " + runner.CONF + " or with --flow")
        return 1
    try:
        k = int(k or conf.get("k") or 1)
    except ValueError:
        print("--k is a number of runs per task")
        return 1
    if k < 1:
        print("--k is at least 1")
        return 1
    try:
        spec = config(flow)
    except (FileNotFoundError, ValueError) as e:
        print("no flow " + flow + " to bench: " + str(e))
        return 1
    provider = conf.get("provider") or spec.get("provider") or {}
    if provider.get("provider") != FAKE and "--live" not in argv:
        print("the set runs on " + str(provider.get("provider") or "the "
              "flow's own provider") + ", which calls a real model. --live "
              "runs it, and it is charged")
        return 1
    print("bench " + flow + " over " + str(len(tasks)) + " tasks, k " + str(k))
    rows = runner.run(flow, provider, tasks, k)
    total = scorer.summary(rows, k)
    blob = {"flow": flow, "set": folder.name, "k": k,
            "date": datetime.datetime.now().isoformat(timespec="seconds"),
            "summary": total, "runs": rows}
    path = Path(out) if out else (
        Path(state.RUNS) / "bench" / (folder.name + "-"
                                      + datetime.datetime.now()
                                      .strftime("%Y%m%d-%H%M%S") + ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    print("")
    print(runner.table(flow, rows, total))
    print("")
    print("scores: " + str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
