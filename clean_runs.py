import sys
from pathlib import Path

# runs/ is already at 80 files and i have had this a week

runs = Path("runs")
keep = int(sys.argv[1]) if len(sys.argv) > 1 else 30

if not runs.exists():
    print("no runs yet")
    sys.exit(0)

files = sorted(runs.iterdir(), key=lambda f: f.stat().st_mtime)
old = files[:-keep] if len(files) > keep else []

for f in old:
    f.unlink()

print("deleted " + str(len(old)) + ", kept " + str(len(files) - len(old)))
