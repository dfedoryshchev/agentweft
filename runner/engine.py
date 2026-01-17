import concurrent.futures
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

from roles import resolver

from .config import config, due, fanout_step, steps, verdict
from .handoff import EMPTY, Handoff
from .errors import Fatal, classify
from . import prompts
from .prompts import flow_path, load_prompt, read
from . import resume, router
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


def call(prompt, timeout=None, cap=3, step="?"):
    def once():
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode == 0:
            return True, r.stdout
        kind = classify(r.stderr)
        print("step " + step + " failed (" + kind.__name__.lower() + "): "
              + r.stderr.strip()[:200])
        if kind is Fatal:
            # going again will not help and it still costs
            raise Fatal(r.stderr.strip()[:200])
        return False, r.stdout

    return retry(once, cap)


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
        self.timeout = int(fm.get("timeout", 300))
        self.retries = int(fm.get("retries", 3))
        self.workers = int(fm.get("workers", 3))
        self.fan = fanout_step(flow)

    def step(self, step, previous=EMPTY, extra=""):
        role = step[:-3]
        prompt = load_prompt(self.flow, step, self.by_role[role])
        if extra:
            prompt = prompt + extra
        prompt = prompt + previous.as_prompt()
        text = call(prompt, timeout=self.timeout, cap=self.retries, step=step)
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
    width = min(run.workers, len(tasks)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        parts = list(pool.map(one, tasks))
    return Handoff("worker", "\n\n".join(parts), meta={"tasks": len(tasks)})


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
    fm = config(flow)
    by_role = resolver.resolve(fm.raw, flow_path(flow), fm.promises.as_prompt())
    if not due(fm) and "--force" not in sys.argv:
        print(flow + " is not due today, use --force")
        return
    run = Run(flow, fm, by_role)
    route = router.Router(fm, cap=2)
    started = datetime.datetime.now()
    run_id = flow + "-" + started.strftime("%Y-%m-%d-%H%M%S")
    goes = 0
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
        if seen and step == "planner.md":
            extra = "\n\nthe last run was " + seen + \
                ". only tell me what is different since then."
        out = run.step(step, previous=out, extra=extra)
        step_dir = Path("runs") / run_id
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / step).write_text(out.output, encoding="utf-8")

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
        f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + config(flow).name
                + ("  ok (resumed)  " if pick_up else "  ok  ")
                + str(int((datetime.datetime.now() - started).total_seconds())) + "s  "
                + path.name + "\n")
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
