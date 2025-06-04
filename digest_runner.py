# bash cannot pull the three lists apart without turning into awk soup.
# digest only, the other two still go through run.sh.
import subprocess

FLOW_DIR = "flows/weekly-digest"


def read(name):
    f = open(FLOW_DIR + "/" + name)
    text = f.read()
    f.close()
    return text

def call(prompt):
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
    if r.returncode != 0:
        print("cli failed")
        print(r.stderr)
        return ""
    return r.stdout


def items(text):
    lines = text.split("\n")
    # last one is the empty string after the final newline and the one before
    # it is the blank separator, neither of those are items
    lines = lines[:-2]
    out = []
    for line in lines:
        if line.startswith("- "):
            out.append(line[2:])
    return out


def main():
    prompt = read("prompt.md") + "\n\n" + read("instructions.md")
    out = call(prompt)
    for section in out.split("## "):
        if not section.strip():
            continue
        name = section.split("\n")[0]
        print("## " + name)
        for it in items(section):
            print("  - " + it)
        print("")


main()
