import subprocess
import sys
from pathlib import Path

# not sure this belongs in here at all. windows task scheduler already does
# this and better. leaving it while i think about it.
#
# if it stays it wants --force, otherwise the sunday-only flows never run
# from it.


def needs_task(flow):
    """-> whether the flow will not start without --task.

    a flow this cannot read is started anyway, so run.py says what is wrong
    with it in the place it always has.
    """
    from agentweft.runner import task
    from agentweft.runner.config import config
    from agentweft.runner.prompts import flow_path

    try:
        return bool(task.places(flow_path(flow), config(flow)))
    except Exception:
        return False


def main():
    for flow in sorted(p.name for p in Path("flows").iterdir()
                       if not p.name.startswith("_")):
        print("== " + flow)
        if needs_task(flow):
            print(flow + " takes a task, so cron does not start it. run it "
                  "with --task when there is one")
            continue
        subprocess.run([sys.executable, "run.py", flow])


if __name__ == "__main__":
    main()
