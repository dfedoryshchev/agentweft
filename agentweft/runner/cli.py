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


def need(n, usage):
    """the args a command cannot run without. forgetting one used to print a
    traceback at you, which reads like the tool broke rather than the call."""
    if len(sys.argv) <= n:
        print("usage: " + usage)
        return False
    return True


def cmd_show():
    if not need(2, "python run.py show <flow>"):
        return 1
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
  python run.py provider         is each configured provider usable
  python run.py step <flow> <role>   one step, reading stdin, writing nothing
  python run.py workflow          the phase list, and where it stops
  python rollup.py [--flow x] [--failed]

--force   ignore the schedule
--resume  pick up the last failed run of that flow where it died""")
    return 0


def cmd_step():
    """python run.py step <flow> <role> - one step, nothing written down.

    debugging a prompt meant running the whole flow and paying for all of it.
    """
    if not need(3, "python run.py step <flow> <role>"):
        return 1

    import os

    from agentweft.roles import resolver

    from . import prompts
    from .config import config
    from .engine import Run, load_env
    from .handoff import Handoff

    load_env()
    flow, role = sys.argv[2], sys.argv[3]
    spec = config(flow)
    by_role = resolver.resolve(spec.raw, prompts.flow_path(flow),
                               spec.promises.as_prompt())
    run = Run(flow, spec, by_role)
    previous = ""
    if not os.isatty(0):
        previous = sys.stdin.read()
    out = run.step(role + ".md", previous=Handoff("stdin", previous))
    print(out.output)
    return 0


def cmd_workflow():
    """python run.py workflow - print the phase list i brought over.

    it reads and it prints. nothing here runs a phase: the runner executes a
    flow, and a phase is not a flow yet. this is so the file is at least
    visible from the outside instead of being a diagram i remember.
    """
    from agentweft.orchestrate import workflow

    wf = workflow.load()
    print(wf.name + "  (lead: " + wf.lead + ")")
    for phase in wf.phases:
        seats = ", ".join(str(a) for a in phase.agents)
        line = "  " + phase.name + "  [" + seats + "]"
        if phase.loop > 1:
            line += "  x" + str(phase.loop)
        if phase.sequential:
            line += "  one at a time"
        print(line)
        if phase.entry:
            print("      in:  " + phase.entry)
        if phase.produces:
            print("      ->   " + phase.produces)
        if phase.exit:
            print("      out: " + phase.exit)
        if phase.gate:
            print("      STOPS, waits for " + phase.gate)
    return 0


def cmd_provider():
    """is everything configured actually usable, without spending anything."""
    from agentweft import providers

    from .config import config
    from .engine import load_env

    load_env()
    seen = {}
    for name in flows():
        try:
            spec = config(name)
        except Exception:
            continue
        configs = [spec.get("provider") or {}]
        configs += [s["provider"] for s in spec.steps if s.get("provider")]
        for c in configs:
            key = str(sorted((c or {}).items()))
            if key in seen:
                continue
            seen[key] = True
            p = providers.build(c or {})
            ok, detail = p.check()
            print(("  ok   " if ok else "  FAIL ") + p.name + "  " + detail)
    return 0


def cmd_spend():
    journal = Path("runs") / "journal.md"
    if not journal.exists():
        print("no runs yet")
        return 0
    for line in journal.read_text().split("\n")[-20:]:
        if "calls" in line:
            print(line)
    return 0


def entrypoint():
    """what `agentweft` on the path calls."""
    from .engine import main as _main

    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        return COMMANDS[sys.argv[1]]()
    return _main()


COMMANDS = {"list": cmd_list, "show": cmd_show, "help": cmd_help, "spend": cmd_spend,
            "step": cmd_step, "provider": cmd_provider, "workflow": cmd_workflow,
            "--help": cmd_help, "-h": cmd_help}
