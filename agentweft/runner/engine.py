import concurrent.futures
import datetime
import os
import sys
import time
from pathlib import Path

from agentweft.roles import resolver

from .config import config, due, fanout_step, steps, verdict
from agentweft import providers
from agentweft.guardrails import defaults, gates, promises
from agentweft.mcp import context
from agentweft.guardrails.budget import Budget

from .handoff import EMPTY, Handoff
from .errors import Fatal, classify
from . import prompts
from .prompts import flow_path, load_prompt, read
from . import resume, router
from .settings import get as setting  # noqa: F401
from . import settings
from .state import load_state, save_state

from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env():
    # not worth a dependency for six lines
    if not os.path.exists(".env"):
        return
    for line in open(".env"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        os.environ[k] = v


def retry(fn, cap=3, sleep=time.sleep):
    tries = 0
    wait = 2
    while tries < cap:
        ok, out = fn()
        if ok:
            return out
        tries = tries + 1
        print("cli failed, waiting " + str(wait) + "s")
        sleep(wait)
        wait = wait * 2
    print("giving up")
    return ""


CACHE = {}


def call(prompt, timeout=None, cap=3, step="?", provider=None):
    # the same planner prompt twice in one evening is the same answer. a redo
    # re-runs the whole flow and most of it has not changed.
    if prompt in CACHE:
        print("step " + step + " came from the cache")
        return CACHE[prompt], True
    p = provider or providers.build({})

    def once():
        reply = p.ask(prompt, timeout=timeout)
        if reply:
            return True, reply.text
        kind = classify(reply.detail)
        print("step " + step + " failed (" + kind.__name__.lower() + "): "
              + reply.detail)
        if kind is Fatal:
            # going again will not help and it still costs
            raise Fatal(reply.detail)
        return False, reply.text

    answer = retry(once, cap)
    CACHE[prompt] = answer
    return answer, False


SEV = ("high", "med", "low")


def is_graded(line):
    return any(line.startswith("[" + s + "]") for s in SEV)


def by_severity(lines):
    out = []
    for s in SEV:
        for line in lines:
            if line.startswith("[" + s + "]"):
                out.append(line)
    for line in lines:
        if not is_graded(line):
            out.append(line)
    return out


def items(text):
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:])
    return out


def write_index(line):
    index = Path("runs") / "index.md"
    index.parent.mkdir(exist_ok=True)
    lines = []
    if index.exists():
        lines = [l for l in index.read_text().split("\n") if l.strip()]
    lines.append(line)
    lines.sort()
    index.write_text("\n".join(lines) + "\n")


def next_run_path(flow):
    runs = Path("runs")
    runs.mkdir(exist_ok=True)
    day = datetime.date.today().isoformat()
    stem = flow + "-" + day
    n = 1
    for f in runs.iterdir():
        if f.name.startswith(stem):
            n = n + 1
    return runs / (stem + "-" + str(n) + ".md")


class Run(object):
    """everything a step needs, built once. fm and by_role were being threaded
    through five functions just so two of them could read a timeout."""

    def __init__(self, flow, fm, by_role):
        self.flow = flow
        self.fm = fm
        self.by_role = by_role
        self.timeout = int(settings.get("timeout", flow=fm))
        self.retries = int(settings.get("retries", flow=fm))
        self.workers = int(settings.get("workers", flow=fm))
        self.fan = fanout_step(flow)
        self.budget = Budget(*defaults.for_flow(fm))
        self.provider = providers.build(fm.get("provider") or {})
        self.by_step = {}
        for s in fm.steps:
            if s.get("provider"):
                self.by_step[s.get("prompt", s["role"] + ".md")] = \
                    providers.build(s["provider"])

    def gates_for(self, step):
        for s in self.fm.steps:
            if s.get("prompt", s["role"] + ".md") == step:
                return [gates.build(g) for g in (s.get("gates") or [])]
        return []

    def width_for(self, role):
        for s in self.fm.steps:
            if s["role"] == role:
                return int(settings.get("workers", step=s, flow=self.fm))
        return 1

    def step(self, step, previous=EMPTY, extra=""):
        role = step[:-3]
        prompt = load_prompt(self.flow, step, self.by_role[role])
        if extra:
            prompt = prompt + extra
        prompt = prompt + previous.as_prompt()
        text, cached = call(prompt, timeout=self.timeout, cap=self.retries, step=step,
                            provider=self.by_step.get(step, self.provider))
        if not cached:
            # a cached answer costs nothing and was counting against the cap,
            # so a flow with a redo in it hit the ceiling on work it never did
            used = self.by_step.get(step, self.provider)
            self.budget.charge(prompt, text, provider=used.name)
        return Handoff(role, text, verdict(text))


def run_steps(run, names, note=EMPTY):
    """the redo path. same pipeline as the first pass, fanout included - a redo
    that skips the fanout is not the same flow."""
    out = note
    for step in names:
        if run.fan and step == run.fan + ".md":
            out = run_fanout(run, out)
            continue
        out = run.step(step, previous=out)
    return out


def run_fanout(run, plan):
    tasks = [l for l in plan.output.split("\n") if "|" in l]

    def one(task):
        return run.step("worker.md",
                        extra="\n\nyour task, only this one:\n\n" + task).output

    # three workers and two tasks means an idle thread and a pool i paid to
    # build. no point.
    # planner 1, workers N, reviewer 1. the fanned out step is the only one
    # that gets to be plural, and it says so itself.
    width = min(run.width_for("worker"), len(tasks)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        parts = list(pool.map(one, tasks))
    return Handoff("worker", "\n\n".join(parts), meta={"tasks": len(tasks)})


def run_once(flow):
    """run a flow and hand back what it produced plus what it cost. the eval
    harness wants the output, not the printing."""
    fm = config(flow)
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    run = Run(flow, fm, by_role)
    route = router.Router(fm, cap=2)
    out = EMPTY
    step = steps(flow)[0]
    while step:
        if run.fan and step == run.fan + ".md":
            out = run_fanout(run, out)
            step = route.next(step, out)
            continue
        out = run.step(step, previous=out)
        if not out:
            break
        step = route.next(step, out)
    return out.output, run.budget


def main():
    load_env()
    if "--flows" in sys.argv:
        prompts.FLOW_ROOT[0] = sys.argv[sys.argv.index("--flows") + 1]
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    pick_up = None
    if "--resume" in sys.argv:
        i = sys.argv.index("--resume")
        pick_up = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if pick_up is None:
            ids = resume.runs_for(flow)
            pick_up = ids[-1] if ids else None
    try:
        fm = config(flow)
    except FileNotFoundError:
        known = ", ".join(sorted(p.name for p in Path(prompts.FLOW_ROOT[0]).iterdir()
                                 if p.is_dir() and not p.name.startswith("_")))
        print("no flow called " + flow + ". there is: " + known)
        return 1
    except ValueError as e:
        print(flow + "/flow.yaml is wrong: " + str(e))
        return 1
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    if not due(fm) and "--force" not in sys.argv:
        print(flow + " is not due today, use --force")
        return
    run = Run(flow, fm, by_role)
    route = router.Router(fm, cap=2)
    started = datetime.datetime.now()
    run_id = flow + "-" + started.strftime("%Y-%m-%d-%H%M%S")
    out = EMPTY
    todo = steps(flow)
    if pick_up:
        failed = resume.last_failure(fm["name"])
        if failed:
            todo = resume.remaining(todo, failed[0])
            before = steps(flow)[:len(steps(flow)) - len(todo)]
            if before:
                out = Handoff(before[-1][:-3], resume.step_output(pick_up, before[-1]))
            print("picking " + pick_up + " up at " + todo[0])
    seen = load_state(flow).get("last_run")
    fan = fanout_step(flow)
    step = todo[0]
    while step:
        if fan and step == fan + ".md":
            out = run_fanout(run, out)
            step = route.next(step, out)
            continue
        extra = ""
        if step == "planner.md" and fm.get("context"):
            text, why = context.risk_map(fm.get("context"))
            if why:
                print("no risk map: " + why)
            extra = extra + context.as_prompt(text)
        if seen and step == "planner.md":
            extra = "\n\nthe last run was " + seen + \
                ". only tell me what is different since then."
        out = run.step(step, previous=out, extra=extra)
        step_dir = Path("runs") / run_id
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / step).write_text(out.output, encoding="utf-8")

        spent = run.budget.over()
        if spent:
            print("stopping: " + spent)
            write_index("OVER  " + flow + "  " + spent)
            f = open(Path("runs") / "journal.md", "a")
            f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + fm["name"]
                    + "  over budget at " + step + "  "
                    + str(int((datetime.datetime.now() - started).total_seconds())) + "s\n")
            f.close()
            return

        checks = run.gates_for(step)
        results = [g.run(out.output) for g in checks]
        for r in results:
            print("  " + repr(r))
        if results:
            step_dir = Path("runs") / run_id
            step_dir.mkdir(parents=True, exist_ok=True)
            with open(step_dir / "gates.md", "a") as gf:
                gf.write("## " + step + "\n")
                for r in results:
                    gf.write(repr(r) + "\n")
        failed_gates = [r for r in results if not r.ok]
        if failed_gates:
            # a gate is not advice. it was failing the STEP, which meant the
            # run carried on and wrote the output anyway.
            print("gate failed at " + step + ", stopping")
            write_index("GATE  " + flow + "  " + failed_gates[0].gate + " at " + step)
            f = open(Path("runs") / "journal.md", "a")
            f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + fm["name"]
                    + "  gate " + failed_gates[0].gate + " failed at " + step + "  "
                    + str(int((datetime.datetime.now() - started).total_seconds())) + "s\n")
            f.close()
            return

        blocked = route.gate(step, out)
        if blocked:
            print(blocked + " - not going on")
            out = Handoff(out.role, "", verdict="redo", meta={"blocked": blocked})

        if not out:
            print("run stopped at " + step)
            runs = Path("runs")
            runs.mkdir(exist_ok=True)
            write_index("FAILED  " + flow + "  at " + step)
            f = open(runs / "journal.md", "a")
            f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + fm["name"]
                    + "  failed at " + step + "  "
                    + str(int((datetime.datetime.now() - started).total_seconds())) + "s\n")
            f.close()
            return

        nxt = route.next(step, out)
        if out.verdict == "redo" and nxt:
            print("sent back to " + nxt)
        step = nxt

    broken = promises.failures(out.output, fm.promises.invariants)
    for inv, detail in broken:
        print("promise broken: " + inv + " (" + detail + ")")
        write_index("BROKE  " + flow + "  " + inv)

    path = next_run_path(flow)
    f = open(path, "w")
    f.write(out.output)
    f.close()
    print("saved " + str(path))

    save_state(flow, {"last_run": path.name,
                      "at": datetime.datetime.now().isoformat()})

    # code-review runs per diff, several times an hour. it drowns the weekly
    # rollup and none of it is interesting a day later.
    if fm.get("journal", True):
        journal = Path("runs") / "journal.md"
        f = open(journal, "a")
        status = "ok"
        if pick_up:
            status = "ok (resumed)"
        if broken:
            status = "ok, " + str(len(broken)) + " promise(s) broken"
        f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + config(flow).name
                + "  " + status + "  "
                + str(int((datetime.datetime.now() - started).total_seconds())) + "s  "
                + path.name + "  " + run.budget.summary() + "\n")
        f.close()

    write_index(path.name + "  " + flow + "  " + str(len(steps(flow))) + " steps")

    if flow == "weekly-digest":
        for section in out.output.split("## "):
            if not section.strip():
                continue
            name = section.split("\n")[0]
            print("## " + name)
            for it in items(section):
                print("  - " + it)
            print("")
    elif flow == "ops-check":
        for line in by_severity(items(out.output)):
            print("- " + line)
    else:
        print(out.output)


if __name__ == "__main__":
    main()
