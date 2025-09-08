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


def config(flow):
    return yaml.safe_load(flow_path(flow, "flow.yaml").read_text())


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

    width = int(fm.get("workers", 3))
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        parts = list(pool.map(one, tasks))
    return "\n\n".join(parts)


def steps(flow):
    fm = config(flow)
    return [s.get("prompt", s["role"] + ".md") for s in fm["steps"]]


def main():
    load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    fm = config(flow)
    frag = Path("fragments")
    shared = ""
    for name in ["role-header", "output-rules", "no-preamble", "no-guessing", "header"]:
        shared = shared + (frag / (name + ".md")).read_text()
    rules = shared + read(flow, "instructions.md")
    out = ""
    seen = load_state().get(flow, {}).get("last_run")
    fan = fanout_step(flow)
    for step in steps(flow):
        if fan and step == fan + ".md":
            out = run_fanout(flow, rules, out, fm)
            continue
        prompt = read(flow, step) + "\n\n" + rules
        for key in ["INBOX", "LOGS", "WATCH"]:
            prompt = prompt.replace("{" + key + "}", os.environ.get(key, ""))
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
        if not out:
            print("run stopped at " + step)
            index = Path("runs") / "index.md"
            index.parent.mkdir(exist_ok=True)
            f = open(index, "a")
            f.write("FAILED  " + flow + "  at " + step + "\n")
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
