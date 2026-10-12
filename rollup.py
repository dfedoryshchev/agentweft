import datetime
import sys
from collections import Counter

from agentweft.runner import state, stops

# what did the week actually do. reads runs/journal.md, one line per run.


def week(lines, since, only_flow=None, only_stopped=False):
    """-> what the journal lines since `since` add up to.

    a run is the line that says how it ended; the `running` line in front of
    it is not a second run. one that began and never wrote an end is counted
    on its own, because nothing knows why it stopped.
    """
    runs = Counter()
    stopped = Counter()
    resumed = Counter()
    seconds = Counter()
    causes = Counter(dict.fromkeys(stops.CAUSES, 0))
    began = {}
    ended = set()
    for text in lines:
        line = stops.read(text)
        if line is None:
            continue
        if stops.parse_when(line.when) < since:
            continue
        name = line.flow
        if only_flow and name != only_flow:
            continue
        if line.kind == "running":
            began[line.run] = name
            continue
        if line.run:
            ended.add(line.run)
        if only_stopped and line.kind != "stop":
            continue
        runs[name] += 1
        if "resumed" in line.status:
            resumed[name] += 1
        if line.kind == "stop":
            stopped[name] += 1
            causes[stops.checked(line.cause)] += 1
        seconds[name] += int(line.secs.rstrip("s"))
    unfinished = [run for run in began if run not in ended]
    return {"runs": runs, "stopped": stopped, "resumed": resumed,
            "seconds": seconds, "causes": causes, "unfinished": unfinished}


def by_week(lines):
    weeks = Counter()
    for text in lines:
        line = stops.read(text)
        if line is None or line.kind == "running":
            continue
        weeks[stops.parse_when(line.when).strftime("%Y w%W")] += 1
    return weeks


def main(argv=None):
    argv = sys.argv if argv is None else argv
    journal = state.RUNS / "journal.md"
    if not journal.exists():
        print("no journal yet")
        return 0
    only_flow = None
    for i, a in enumerate(argv):
        if a == "--flow" and len(argv) > i + 1:
            only_flow = argv[i + 1]
    lines = journal.read_text(encoding="utf-8").split("\n")
    since = datetime.datetime.now() - datetime.timedelta(days=7)
    got = week(lines, since, only_flow, only_stopped="--failed" in argv)

    print("last 7 days")
    print("")
    # a resumed run writes its own line, so the count is runs-plus-resumes. showing
    # the resumes separately at least makes the number explainable.
    for name, n in got["runs"].most_common():
        avg = got["seconds"][name] // n
        print("  " + name + "  " + str(n) + " runs, " + str(got["stopped"][name])
              + " stopped, " + str(avg) + "s avg"
              + ("  (" + str(got["resumed"][name]) + " of them resumes)"
                 if got["resumed"][name] else ""))
    if got["unfinished"]:
        print("  " + str(len(got["unfinished"]))
              + " started and never wrote how it ended")

    print("")
    print("stops by cause")
    counted = [(c, n) for c, n in got["causes"].items() if n]
    for cause, n in counted:
        print("  " + cause + "  " + str(n))
    if not counted:
        print("  none")

    print("")
    print("by week")
    weeks = by_week(lines)
    for wk in sorted(weeks)[-8:]:
        print("  " + wk + "  " + str(weeks[wk]) + " runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
