import subprocess
import sys
from pathlib import Path

# not sure this belongs in here at all. windows task scheduler already does
# this and better. leaving it while i think about it.

for flow in sorted(p.name for p in Path("flows").iterdir() if not p.name.startswith("_")):
    print("== " + flow)
    subprocess.run([sys.executable, "runner.py", flow])
