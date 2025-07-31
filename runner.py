# everything goes through here now. bash could not pull the three lists apart
# without turning into awk soup.
import datetime
import os
import time
import subprocess
import sys
from pathlib import Path


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

TRIES = 0


def retry(fn, cap=3):
    global TRIES
    wait = 2
    while TRIES < cap:
        ok, out = fn()
        if ok:
            return out
        TRIES = TRIES + 1
        print("cli failed, waiting " + str(wait) + "s")
        time.sleep(wait)
        wait = wait * 2
    print("giving up")
    return ""


def call(prompt, timeout=None, cap=3):
    def once():
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                           timeout=timeout)
        if r.returncode != 0:
            print(r.stderr)
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


def frontmatter(flow):
    text = read(flow, "flow.md")
    if not text.startswith("---"):
        return {}
    block = text.split("---")[1]
    out = {}
    for line in block.strip().split("\n"):
        if not line.strip():
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def steps(flow):
    fm = frontmatter(flow)
    names = fm.get("steps", "prompt").split(",")
    return [n.strip() + ".md" for n in names]


def main():
    load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    fm = frontmatter(flow)
    frag = Path("fragments")
    shared = (frag / "role-header.md").read_text() + (frag / "output-rules.md").read_text() \
        + (frag / "header.md").read_text()
    rules = shared + read(flow, "instructions.md")
    out = ""
    for step in steps(flow):
        prompt = read(flow, step) + "\n\n" + rules
        for key in ["INBOX", "LOGS", "WATCH"]:
            prompt = prompt.replace("{" + key + "}", os.environ.get(key, ""))
        if out:
            prompt = prompt + "\n\nhere is what you wrote last pass:\n\n" + out
        out = call(prompt, timeout=int(fm.get("timeout", 300)),
                   cap=int(fm.get("retries", 3)))
    path = next_run_path(flow)
    f = open(path, "w")
    f.write(out)
    f.close()
    print("saved " + str(path))

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
