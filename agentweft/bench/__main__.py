import datetime
import json
import sys
from pathlib import Path

from . import history, ladder, pairs, retrogold, runner, scorer

USAGE = ("usage: python -m agentweft.bench <set> [--k <n>] [--flow <flow>]"
         " [--out <file>] [--scores <file>] [--live] [--mutants]\n"
         "       python -m agentweft.bench --compare [--base <sha>]"
         " [--head <sha>] [--flow <flow>] [--scores <file>]\n"
         "       python -m agentweft.bench --retro <cases> [--k <n>]"
         " [--out <file>] [--live]\n"
         "       python -m agentweft.bench --pairs <set> [--k <n>]"
         " [--flow <flow>] [--twin] [--out <file>] [--live]\n"
         "       python -m agentweft.bench --ladder <run folder>..."
         " [--hidden <verdicts.json>]")
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
    if "--compare" in argv:
        return compared(argv)
    for flag, mode in (("--retro", retrogold), ("--pairs", pairs),
                       ("--ladder", ladder)):
        if flag in argv:
            try:
                return mode.main(argv, valued, fake=FAKE)
            except ValueError as e:
                print(str(e))
                return 1
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
        scores = history.place(valued(argv, "--scores"))
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
    date = datetime.datetime.now()
    path = Path(out) if out else (
        Path(state.RUNS) / "bench" / (folder.name + "-"
                                      + date.strftime("%Y%m%d-%H%M%S")
                                      + ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)

    def scored(rows):
        blob = {"flow": flow, "set": folder.name, "k": k,
                "date": date.isoformat(timespec="seconds"),
                "summary": scorer.summary(rows, k), "runs": rows}
        path.write_text(json.dumps(blob, indent=2), encoding="utf-8")

    rows = runner.run(flow, provider, tasks, k, mutate="--mutants" in argv,
                      scored=scored)
    total = scorer.summary(rows, k)
    print("")
    print(runner.table(flow, rows, total))
    print("")
    print("scores: " + str(path))
    print(history.keep(scores, lambda sha, dirty: history.from_bench(
        sha, dirty, flow, folder.name, rows)))
    return 0


def compared(argv):
    """-> 1 when a task that passed on the base fails on every repeat of the
    head, or a record either side needs is missing or unreadable."""
    try:
        scores = history.place(valued(argv, "--scores"))
        base, head, flow = (valued(argv, f) for f in
                            ("--base", "--head", "--flow"))
    except ValueError as e:
        print(str(e))
        return 1
    records, problems = history.read(scores)
    for p in problems:
        print(p)
    head = head or history.commit(scores)[0]
    if not head:
        print("no commit here: name the head with --head")
        return 1
    try:
        head = history.named(records, head)
        base = (history.named(records, base) if base
                else history.previous(records, head))
    except ValueError as e:
        print(str(e))
        return 1
    if base is None:
        print("no commit before " + head[:7] + " has records: name one with"
              " --base")
        return 1
    lines, failed = history.compare(records, base, head, flow)
    print("\n".join(lines))
    return 1 if failed or problems else 0


if __name__ == "__main__":
    sys.exit(main())
