# everything goes through here now. bash could not pull the three lists apart
# without turning into awk soup.
import datetime
import os
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
    f = open(Path("flows") / flow / name)
    text = f.read()
    f.close()
    return text

TRIES = 0

def call(prompt):
    global TRIES
    while TRIES < 2:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        TRIES = TRIES + 1
        print("cli failed, going again")
        print(r.stderr)
    print("giving up")
    return ""


def items(text):
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:])
    return out


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


def steps(flow):
    # a flow is one prompt unless there is a critique pass sitting next to it
    if (Path("flows") / flow / "critique.md").exists():
        return ["prompt.md", "critique.md"]
    return ["prompt.md"]


def main():
    load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    rules = read(flow, "instructions.md")
    out = ""
    for step in steps(flow):
        prompt = read(flow, step) + "\n\n" + rules
        for key in ["INBOX", "LOGS", "WATCH"]:
            prompt = prompt.replace("{" + key + "}", os.environ.get(key, ""))
        if out:
            prompt = prompt + "\n\nhere is what you wrote last pass:\n\n" + out
        out = call(prompt)
    path = next_run_path(flow)
    f = open(path, "w")
    f.write(out)
    f.close()
    print("saved " + str(path))

    if flow == "weekly-digest":
        for section in out.split("## "):
            if not section.strip():
                continue
            name = section.split("\n")[0]
            print("## " + name)
            for it in items(section):
                print("  - " + it)
            print("")
    else:
        print(out)


main()
