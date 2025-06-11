# bash cannot pull the three lists apart without turning into awk soup.
# digest only, the other two still go through run.sh.
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


def main():
    load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    prompt = read(flow, "prompt.md") + "\n\n" + read(flow, "instructions.md")
    for key in ["INBOX", "LOGS", "WATCH"]:
        prompt = prompt.replace("{" + key + "}", os.environ.get(key, ""))
    out = call(prompt)
    print(out)
    for section in out.split("## "):
        if not section.strip():
            continue
        name = section.split("\n")[0]
        print("## " + name)
        for it in items(section):
            print("  - " + it)
        print("")


main()
