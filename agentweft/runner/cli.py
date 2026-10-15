import sys
from pathlib import Path

from . import state, task
from .config import config
from .prompts import FLOW_ROOT, flow_path


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
    try:
        spec = config(name)
    except FileNotFoundError:
        print("no flow called " + name + " in " + FLOW_ROOT[0]
              + ". there is: " + ", ".join(flows()))
        return 1
    print(spec.name)
    if spec.promises.inputs:
        print("  in:  " + spec.promises.inputs)
    if spec.promises.outputs:
        print("  out: " + spec.promises.outputs)
    from agentweft.guardrails import promises
    for i, by in promises.shown_by(spec.steps, spec.promises.invariants):
        print("  always: " + i + ("  (shown by " + ", ".join(by) + ")"
                                  if by else ""))
    if spec.get("verify") is not None:
        print("  verify: " + spec.get("verify"))
    where = task.places(flow_path(name), spec)
    if where:
        print("  task: " + task.MARK + " in " + ", ".join(where))
    return 0


def cmd_help():
    print("""usage:
  python run.py <flow> [--force] [--resume [run-id]] [--flows <dir>]
                       [--workdir <dir>]
                       [--task "<text>" | --task-file <path>]
                       [--model-for <role>=<model>,...]
                       [--effort-for <role>=<level>,...]
                       [--skip-tests "<reason>"] [--continue <run|commit>]
                       [--max-calls <n>] [--max-tokens <n>]
                       [--on-stop keep|revert-tests]
  python run.py list              what flows there are
  python run.py show <flow>       what one promises
  python run.py spend            what the last runs cost
  python run.py provider         is each configured provider usable
  python run.py step <flow> <role-or-step>   one step, nothing written down
  python run.py workflow          the phase list, and where it stops
  python run.py vocab             flow words against phase words, counted
  python run.py verify <run-id>   does that run's record still hold
  python rollup.py [--flow x] [--failed]

--force   ignore the schedule
--resume  pick up a run that did not finish, read from its own manifest: the
          one named, or the newest of that flow. one that died starts again
          at the step that died; one that parked for a person carries on at
          the step after it. it keeps the task, the models, the place and what
          the run had spent; a flow edited since then needs --force, and
          so does a run whose record no longer holds (see verify)
--workdir the directory the run works in, over the flow's own `workdir`.
          a resumed run stays in the one it started in
--task    what this run is for: a bug, a feature, a question. it goes where
          the flow wrote {TASK}, and a flow without one refuses it. a flow
          with one does not start without it. a resumed run keeps the task
          it started with
--task-file  the same, read from a UTF-8 file. for anything longer than a
          line
--model-for  the model one role runs on for this run: a tier (high, mid,
          low) or a model id, over the step's and the flow's own. a resumed
          run keeps the ones it started with
--effort-for  how hard one role's model thinks for this run: low, medium,
          high, xhigh or max, over the step's and the flow's own. a step sent
          back goes again one level higher, up to xhigh. a resumed run keeps
          the ones it started with
--skip-tests  run a flow whose steps say what they write without any test
          check: no red test is needed before product code. the reason is
          required and goes into decisions.md and the handoff
--continue  carry the red tests of an earlier run of the same place, or of
          the start commit's tests added since <commit> and any test file
          not committed yet (HEAD for those alone), once each is seen to
          still hold
--max-calls / --max-tokens  the cap for this run, over the flow's own; 0
          is no cap. a run that parked at its cap carries on only with it
          raised, and the change is written to decisions.md
--on-stop  what a run that stops short does with the tests it added or
          changed, over the flow's `on_stop`. either way each one left red
          is named in the handoff; `keep` (the default) leaves them, and
          `revert-tests` puts the test files back to their bytes at the start""")
    return 0


def cmd_step():
    """python run.py step <flow> <role-or-step> - one step, nothing written.

    debugging a prompt meant running the whole flow and paying for all of it.

    a role is enough while it is one step, and a role run twice is the case
    where it is not: `reviewer` is then the first of the pair and the other
    one is only reachable by its own name.
    """
    if not need(3, "python run.py step <flow> <role-or-step>"):
        return 1

    import os

    from agentweft.flow.spec import step_id, steps_named
    from agentweft.roles import resolver

    from . import prompts
    from .config import config
    from .engine import Run, load_env
    from .handoff import Handoff

    load_env()
    flow, name = sys.argv[2], sys.argv[3]
    try:
        asked = task.given(sys.argv)
    except ValueError as e:
        print(str(e))
        return 1
    spec = config(flow)
    by_role = resolver.resolve(spec.raw, prompts.flow_path(flow),
                               spec.promises.as_prompt())
    run = Run(flow, spec, by_role, task=asked)
    named = steps_named(spec.steps, name)
    step = step_id(named[0]) if named else name + ".md"
    previous = ""
    if not os.isatty(0):
        previous = sys.stdin.read()
    from .errors import Outage

    try:
        out = run.step(step, previous=Handoff("stdin", previous))
    except Outage as e:
        print("provider outage: limit reached, resets " + e.resets)
        return 2
    print(out.output)
    return 0


def cmd_workflow():
    """python run.py workflow - print the phase list i brought over.

    it reads and it prints. a phase loads as a flow spec now, and that changed
    nothing about running one: the runner executes a flow it is asked for, and
    nothing asks it for these. this is so the file is at least visible from the
    outside instead of being a diagram i remember.
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


def cmd_vocab():
    """python run.py vocab - the flow vocabulary against the phase one.

    the docs say a phase is a flow. this prints the arithmetic behind that:
    what both sides have a name for, what only one of them does, the two words
    that mean different things depending on which file you are in, and what
    the merge could not carry across.
    """
    from agentweft.orchestrate import compare

    for line in compare.report():
        print(line)
    return 0


def cmd_provider():
    """is everything configured actually usable, without spending anything.

    a tier counts as configuration. a step asking for `high` resolves a
    different model from the same provider block, so it is a different answer
    to "is this usable" and it gets its own line - otherwise a flow with no
    MODEL_HIGH anywhere passes this and fails at the step.
    """
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
        configs = [(spec.get("provider") or {}, "")]
        for s in spec.steps:
            if not s.get("provider") and not s.get("model"):
                continue
            configs.append((s.get("provider") or spec.get("provider") or {},
                            s.get("model", "")))
        for c, tier in configs:
            p = providers.build(c or {}, tier=tier)
            key = p.name + " " + str(sorted(p.opts.items()))
            if key in seen:
                continue
            seen[key] = True
            ok, detail = p.check()
            print(("  ok   " if ok else "  FAIL ") + p.name
                  + (" " + tier if tier else "") + "  " + detail)
    return 0


def cmd_spend():
    """the last twenty runs that say what they spent, finished and stopped
    alike since a run that stopped short was paid for all the same, then the
    same runs per flow and per provider."""
    from . import spend

    for line in spend.report(state.RUNS):
        print(line)
    return 0


def cmd_verify():
    """python run.py verify <run id> - does the run's record still hold.

    reads its steps.jsonl back against the chain each line carries, the head
    the manifest kept and the files the last line names, and says the first
    line that was edited, dropped or put out of order. exit 1 when it breaks
    or there is nothing to check.
    """
    if not need(2, "python run.py verify <run id>"):
        return 1
    from . import chain

    run_id = sys.argv[2]
    folder = state.RUNS / run_id
    if not folder.is_dir():
        print("no run called " + run_id + " in " + str(state.RUNS))
        return 1
    found = chain.verify(folder)
    if found.broken:
        print(run_id + ": broken: " + found.broken)
        return 1
    if found.unchained:
        print(run_id + ": " + str(found.lines) + " lines written before the"
              " record was chained, so there is nothing to check them by")
        return 1
    if not found.lines:
        print(run_id + ": no steps.jsonl lines to check")
        return 1
    print(run_id + ": holds, " + str(found.lines) + " lines, head "
          + found.head[:16])
    return 0


def command(name):
    """-> the exit code of one of COMMANDS. `--flows` is read here, so it
    names the folder for every command and not only for a run."""
    if "--flows" in sys.argv:
        i = sys.argv.index("--flows")
        if len(sys.argv) <= i + 1:
            print("--flows needs a directory")
            return 1
        FLOW_ROOT[0] = sys.argv[i + 1]
    return COMMANDS[name]()


def entrypoint():
    """what `agentweft` on the path calls."""
    from .engine import main as _main

    if len(sys.argv) > 1 and sys.argv[1] in COMMANDS:
        return command(sys.argv[1])
    return _main()


COMMANDS = {"list": cmd_list, "show": cmd_show, "help": cmd_help, "spend": cmd_spend,
            "step": cmd_step, "provider": cmd_provider, "workflow": cmd_workflow,
            "vocab": cmd_vocab, "verify": cmd_verify, "--help": cmd_help,
            "-h": cmd_help}
