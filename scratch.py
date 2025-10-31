import sys
from pathlib import Path

sys.path.insert(0, ".")
from roles import resolver

# how much prompt is boilerplate. every role gets fragments + skills before it
# gets a word of its own.
shared = len(resolver.shared_rules()) + len(resolver.skill_rules())
for f in sorted(Path("flows").iterdir()):
    if f.name.startswith("_"):
        continue
    own = sum(len(p.read_text()) for p in f.glob("*.md"))
    print(f.name, "shared", shared, "own", own)
