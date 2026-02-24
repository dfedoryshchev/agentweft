import sys
from pathlib import Path

from .config import config
from .prompts import FLOW_ROOT


def flows():
    root = Path(FLOW_ROOT[0])
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def cmd_list():
    for name in flows():
        try:
            spec = config(name)
        except Exception as e:
            print(name + "  BROKEN  " + str(e)[:60])
            continue
        roles = ", ".join(s["role"] for s in spec.steps)
        print(name + "  [" + roles + "]  " + (spec.get("schedule") or "on demand"))
    return 0


def cmd_show():
    name = sys.argv[2]
    spec = config(name)
    print(spec.name)
    if spec.promises.inputs:
        print("  in:  " + spec.promises.inputs)
    if spec.promises.outputs:
        print("  out: " + spec.promises.outputs)
    for i in spec.promises.invariants:
        print("  always: " + i)
    return 0


def cmd_help():
    print("""usage:
  python run.py <flow> [--force] [--resume [run-id]] [--flows <dir>]
  python run.py list              what flows there are
  python run.py show <flow>       what one promises
  python run.py spend            what the last runs cost
  python rollup.py [--flow x] [--failed]

--force   ignore the schedule
--resume  pick up the last failed run of that flow where it died""")
    return 0


def cmd_spend():
    from pathlib import Path
    journal = Path("runs") / "journal.md"
    if not journal.exists():
        print("no runs yet")
        return 0
    for line in journal.read_text().split("\n")[-20:]:
        if "calls" in line:
            print(line)
    return 0


COMMANDS = {"list": cmd_list, "show": cmd_show, "help": cmd_help, "spend": cmd_spend,
            "--help": cmd_help, "-h": cmd_help}
