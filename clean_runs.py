import sys
from pathlib import Path

# runs/ is already at 80 files and i have had this a week

runs = Path("runs")
keep = int(sys.argv[1]) if len(sys.argv) > 1 else 30
KEEP_NAMES = ("index.md", "journal.md", "last-step.md")

if not runs.exists():
    print("no runs yet")
    sys.exit(0)

# the old ones had no date in the name, they are all older than anything i
# care about, so they just go
old_format = [f for f in runs.iterdir()
              if f.name not in KEEP_NAMES and f.name.count("-") < 3]
for f in old_format:
    f.unlink()

files = [f for f in runs.iterdir() if f.name not in KEEP_NAMES]
files.sort(key=lambda f: f.stat().st_mtime)
old = files[:-keep] if len(files) > keep else []

for f in old:
    f.unlink()

index = runs / "index.md"
if index.exists():
    names = set(f.name for f in runs.iterdir())
    lines = [l for l in index.read_text().split("\n")
             if l.startswith("FAILED") or l.split("  ")[0] in names]
    index.write_text("\n".join(lines) + "\n")

print("deleted " + str(len(old) + len(old_format))
      + ", kept " + str(len(files) - len(old)))
