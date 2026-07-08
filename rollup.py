import datetime
import sys
from collections import Counter
from pathlib import Path

# what did the week actually do. reads runs/journal.md, one line per run.

journal = Path("runs") / "journal.md"
if not journal.exists():
    print("no journal yet")
    raise SystemExit(0)

since = datetime.datetime.now() - datetime.timedelta(days=7)
only_flow = None
only_failed = "--failed" in sys.argv
for i, a in enumerate(sys.argv):
    if a == "--flow" and len(sys.argv) > i + 1:
        only_flow = sys.argv[i + 1]

runs = Counter()
failed = Counter()
resumed = Counter()
seconds = Counter()

for line in journal.read_text().split("\n"):
    if not line.strip():
        continue
    parts = [p for p in line.split("  ") if p]
    when = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
    if when < since:
        continue
    name = parts[1]
    if only_flow and name != only_flow:
        continue
    if only_failed and not parts[2].startswith("failed"):
        continue
    runs[name] += 1
    if "resumed" in parts[2]:
        resumed[name] += 1
    if parts[2].startswith("failed"):
        failed[name] += 1
    seconds[name] += int(parts[3].rstrip("s"))

print("last 7 days")
print("")
# a resumed run writes its own line, so the count is runs-plus-resumes. showing
# the resumes separately at least makes the number explainable.
for name, n in runs.most_common():
    avg = seconds[name] // n
    print("  " + name + "  " + str(n) + " runs, " + str(failed[name])
          + " failed, " + str(avg) + "s avg"
          + ("  (" + str(resumed[name]) + " of them resumes)" if resumed[name] else ""))

print("")
print("by week")
weeks = Counter()
for line in journal.read_text().split("\n"):
    if not line.strip():
        continue
    parts = [p for p in line.split("  ") if p]
    when = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
    weeks[when.strftime("%Y w%W")] += 1
for wk in sorted(weeks)[-8:]:
    print("  " + wk + "  " + str(weeks[wk]) + " runs")
