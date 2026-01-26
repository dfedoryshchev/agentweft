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
    if parts[2].startswith("failed"):
        failed[name] += 1
    seconds[name] += int(parts[3].rstrip("s"))

print("last 7 days")
print("")
for name, n in runs.most_common():
    avg = seconds[name] // n
    print("  " + name + "  " + str(n) + " runs, " + str(failed[name])
          + " failed, " + str(avg) + "s avg")
