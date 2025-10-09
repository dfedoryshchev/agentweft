# everything goes through here now. bash could not pull the three lists apart
# without turning into awk soup.
import concurrent.futures
import datetime
import json
import os
import tempfile
import time
import subprocess
import sys

import yaml

from roles import resolver
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


def load_prompt(flow, name, rules):
    # pulling this out of main so main stops being the only place that knows
    # how a prompt gets built. half done.
    text = read(flow, name) + "\n\n" + rules
    for key in ["INBOX", "LOGS", "WATCH"]:
        text = text.replace("{" + key + "}", os.environ.get(key, ""))
    return text


def read(flow, name):
    f = open(flow_path(flow, name))
    text = f.read()
    f.close()
    return text

def retry(fn, cap=3):
    tries = 0
    wait = 2
    while tries < cap:
        ok, out = fn()
        if ok:
            return out
        tries = tries + 1
        print("cli failed, waiting " + str(wait) + "s")
        time.sleep(wait)
        wait = wait * 2
    print("giving up")
    return ""


def call(prompt, timeout=None, cap=3, step="?"):
    def once():
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode != 0:
            print("step " + step + " failed: " + r.stderr.strip()[:200])
        return r.returncode == 0, r.stdout

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


def flow_path(flow, *parts):
    return Path("flows").joinpath(flow, *parts)


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


class OrderedLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    # safe_load quietly keeps the LAST of two identical keys, so a flow.yaml
    # with two "steps:" blocks loses the first one and the run order changes
    # under you with nothing in the output to say why
    seen = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in seen:
            raise yaml.YAMLError("duplicate key in flow.yaml: " + str(key))
        seen[key] = loader.construct_object(v, deep=deep)
    return seen


OrderedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


def config(flow):
    return yaml.load(flow_path(flow, "flow.yaml").read_text(), OrderedLoader)


STATE = HERE / "state.json"


def load_state():
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_state(state):
    # write a temp file and swap it in. a half written state.json took me an
    # hour to work out the first time.
    fd, tmp = tempfile.mkstemp(dir=str(STATE.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE)


def run_steps(flow, by_role, fm, names, note=""):
    """the redo path. same pipeline as the first pass, fanout included - a redo
    that skips the fanout is not the same flow."""
    out = note
    fan = fanout_step(flow)
    for step in names:
        if fan and step == fan + ".md":
            out = run_fanout(flow, by_role["worker"], out, fm)
            continue
        prompt = load_prompt(flow, step, by_role[step[:-3]])
        if out:
            prompt = prompt + "\n\nhere is what you wrote last pass:\n\n" + out
        out = call(prompt, timeout=int(fm.get("timeout", 300)),
                   cap=int(fm.get("retries", 3)), step=step)
    return out


def fanout_step(flow):
    for s in config(flow)["steps"]:
        if s.get("fanout"):
            return s["role"]
    return None


def run_fanout(flow, rules, plan, fm):
    tasks = [l for l in plan.split("\n") if "|" in l]

    def one(task):
        prompt = read(flow, "worker.md") + "\n\n" + rules
        for key in ["INBOX", "LOGS", "WATCH"]:
            prompt = prompt.replace("{" + key + "}", os.environ.get(key, ""))
        prompt = prompt + "\n\nyour task, only this one:\n\n" + task
        return call(prompt, timeout=int(fm.get("timeout", 300)),
                    cap=int(fm.get("retries", 3)), step="worker (fanout)")

    # three workers and two tasks means an idle thread and a pool i paid to
    # build. no point.
    width = int(fm.get("workers", 3))
    width = min(width, len(tasks)) or 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        parts = list(pool.map(one, tasks))
    return "\n\n".join(parts)


def verdict(text):
    first = text.strip().split("\n")[0].strip()
    if first.startswith("VERDICT:"):
        return first.split(":", 1)[1].strip()
    return "ok"


def steps(flow):
    fm = config(flow)
    return [s.get("prompt", s["role"] + ".md") for s in fm["steps"]]


def due(fm):
    when = fm.get("schedule")
    if not when:
        return True
    if when == "daily":
        return True
    return datetime.date.today().strftime("%A").lower() == when


def main():
    load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    fm = config(flow)
    by_role = resolver.resolve(fm, Path("flows") / flow)
    if not due(fm) and "--force" not in sys.argv:
        print(flow + " is not due today, use --force")
        return
    started = datetime.datetime.now()
    goes = 0
    out = ""
    seen = load_state().get(flow, {}).get("last_run")
    fan = fanout_step(flow)
    for step in steps(flow):
        if fan and step == fan + ".md":
            out = run_fanout(flow, by_role["worker"], out, fm)
            continue
        prompt = load_prompt(flow, step, by_role[step[:-3]])
        if seen and step == "planner.md":
            prompt = prompt + "\n\nthe last run was " + seen + \
                ". only tell me what is different since then."
        if out:
            # argv blows up on a long digest. writing it out and pointing at it
            # instead, half done, the cli still wants it inline for now.
            last = Path("runs") / "last-step.md"
            last.parent.mkdir(exist_ok=True)
            last.write_text(out, encoding="utf-8")
            prompt = prompt + "\n\nhere is what you wrote last pass:\n\n" + out
        out = call(prompt, timeout=int(fm.get("timeout", 300)),
                   cap=int(fm.get("retries", 3)), step=step)

        # the reviewer can send the work back. it then has to look at what came
        # back, otherwise i am shipping the unreviewed version.
        while step.startswith("reviewer") and verdict(out) == "redo" and goes < 2:
            goes = goes + 1
            print("reviewer said redo, going round again")
            redo = [s for s in steps(flow) if s != step]
            work = run_steps(flow, by_role, fm, redo, note=out)
            again = load_prompt(flow, step, by_role[step[:-3]]) \
                + "\n\nhere is what you wrote last pass:\n\n" + work
            out = call(again, timeout=int(fm.get("timeout", 300)),
                       cap=int(fm.get("retries", 3)), step=step)

        if not out:
            print("run stopped at " + step)
            runs = Path("runs")
            runs.mkdir(exist_ok=True)
            f = open(runs / "index.md", "a")
            f.write("FAILED  " + flow + "  at " + step + "\n")
            f.close()
            f = open(runs / "journal.md", "a")
            f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + fm["name"]
                    + "  failed at " + step + "  "
                    + str(int((datetime.datetime.now() - started).total_seconds())) + "s\n")
            f.close()
            return
    path = next_run_path(flow)
    f = open(path, "w")
    f.write(out)
    f.close()
    print("saved " + str(path))

    state = load_state()
    state.setdefault(flow, {})["last_run"] = path.name
    state[flow]["at"] = datetime.datetime.now().isoformat()
    save_state(state)

    journal = Path("runs") / "journal.md"
    f = open(journal, "a")
    f.write(started.strftime("%Y-%m-%d %H:%M") + "  " + config(flow)["name"] + "  ok  "
            + str(int((datetime.datetime.now() - started).total_seconds())) + "s  "
            + path.name + "\n")
    f.close()

    index = Path("runs") / "index.md"
    lines = []
    if index.exists():
        lines = [l for l in index.read_text().split("\n") if l.strip()]
    lines.append(path.name + "  " + flow + "  " + str(len(steps(flow))) + " steps")
    lines.sort()
    index.write_text("\n".join(lines) + "\n")

    if flow == "weekly-digest":
        for section in out.split("## "):
            if not section.strip():
                continue
            name = section.split("\n")[0]
            print("## " + name)
            for it in items(section):
                print("  - " + it)
            print("")
    elif flow == "ops-check":
        for line in by_severity(items(out)):
            print("- " + line)
    else:
        print(out)


if __name__ == "__main__":
    main()
