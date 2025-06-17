# everything goes through here now. bash could not pull the three lists apart
# without turning into awk soup.
import os
import subprocess
import sys


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
    f = open("flows/" + flow + "/" + name)
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


def steps(flow):
    # a flow is one prompt unless there is a critique pass sitting next to it
    if os.path.exists("flows/" + flow + "/critique.md"):
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
