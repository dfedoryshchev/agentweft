import sys
from pathlib import Path

# runs/ is already at 80 files and i have had this a week

runs = Path("runs")
keep = int(sys.argv[1]) if len(sys.argv) > 1 else 30

if not runs.exists():
    print("no runs yet")
    sys.exit(0)

files = [f for f in runs.iterdir() if f.name != "index.md"]
files.sort(key=lambda f: f.stat().st_mtime)
old = files[:-keep] if len(files) > keep else []

for f in old:
    f.unlink()

# the index still points at files that are gone, drop those lines too
index = runs / "index.md"
if index.exists():
    names = set(f.name for f in runs.iterdir())
    lines = [l for l in index.read_text().split("\n")
             if l.startswith("FAILED") or l.split("  ")[0] in names]
    index.write_text("\n".join(lines) + "\n")

print("deleted " + str(len(old)) + ", kept " + str(len(files) - len(old)))
