"""a shell step writes files with the write tool, not the shell.

a step granted `shell` gets Bash, and Bash can write any file: a redirect, a
heredoc, `sed -i`, a one-line python script. those are also where the time
goes. a heredoc turns the escapes in what it carries into real newlines, a
`sed` that matches nothing changes nothing and says nothing, and a script run
on Windows can flip every line end in the file, and each of those costs the
step turns to notice and undo. the Write and Edit tools have none of them.

so `claude` is handed this module as a PreToolUse hook on Bash and PowerShell
(`providers/cli_provider.py`), in the run's own `--settings`. permission rules
cannot say "Bash, but not the Bash that writes": they match a command by its
prefix. the hook reads the command, and when it writes a file it exits 2 with
a reason naming Write and Edit, which the cli takes as a refusal and shows the
model. every refusal is one json line in the run's `tool-denials.jsonl`, whose
path is the hook's one argument.

it reads the shell's own write syntax and the few programs whose whole job is
writing (`tee`, `cp`, `sed -i`, ...). a program that writes files as a side
effect of something else is not seen. anything the hook cannot read, a call it
cannot parse or an error of its own, is refused too: a check that crashes and
lets the call through is no check.

the same hook also stands on Write, Edit, MultiEdit and NotebookEdit for a
step granted `write` or `edit`, for one thing only: each `--keep <path>`
argument is a file no tool may write, or a folder, ending in `/`, inside which
no tool may write a `.md` file, and the runner passes decisions.md and facts/
in the place (any other file there is the project's own). a
ruling there lets a change stand and a fact tells the next step its way, so
a step writing either would be ruling on its own work
(`guardrails/rulings.py` and `guardrails/factsguard.py` catch whatever gets
past).

the module runs as a script, by path, in a process of its own, so nothing at
its top level may import from the package.
"""
import datetime
import json
import os
import re
import shlex
import sys
import tempfile

FILE = "tool-denials.jsonl"

TOOLS = ("Bash", "PowerShell")
# MultiEdit is an older name the cli still maps onto Edit
EDITORS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
KEEP = "--keep"

SEPARATORS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
SINKS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "nul", "nul:",
         "$null"}
TEMP = re.compile(r"^(\$\{?(TMPDIR|TEMP|TMP)\}?|\$env:(TEMP|TMP)|/tmp)"
                  r"([\\/]|$)", re.I)
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec", "builtin"}
COPIERS = {"cp", "mv", "install", "copy-item", "move-item", "copy", "move"}
PS_WRITERS = {"set-content", "out-file", "add-content", "tee-object", "sc",
              "ac"}
PY_WRITE = re.compile(r"""\bopen\s*\((?:[^()]|\([^()]*\))*?['"][rbt]*[wax]"""
                      r"""|\bmode\s*=\s*['"][^'"]*[wax]"""
                      r"""|\.write_(?:text|bytes)\s*\(""")
NET_WRITE = re.compile(r"\bWriteAll(?:Text|Lines|Bytes)\b|\bAppendAll"
                       r"(?:Text|Lines)\b")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")

REASON = ("refused: `{0}` writes a file from the shell. create a file with the"
          " Write tool and change one with Edit; a step granted neither may"
          " not write files. if the change cannot be made that way, say what"
          " you needed on a NEEDS: line and stop.")
KEPT = ("refused: `{0}` is the run's record of rulings, and only the runner"
        " writes it. a ruling comes from the operator or the lead: ask on a"
        " NEEDS: line and stop.")
KEPT_FACTS = ("refused: `{0}` is in the project's facts, and only the runner"
              " writes them. say what you found in your handoff block, on a"
              " DECIDED or DOUBTS line.")
UNREAD = ("refused: the shell-write check could not read this call ({0}), so"
          " it is not let through. create or change files with the Write or"
          " Edit tool.")


def heredocs(command):
    """-> (the command with every heredoc body taken out, [the bodies])."""
    lines = command.split("\n")
    kept, bodies = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i = i + 1
        for m in HEREDOC.finditer(line):
            word, dash = m.group(3), m.group(1)
            body = []
            while i < len(lines):
                end = lines[i].lstrip("\t") if dash else lines[i]
                i = i + 1
                if end.rstrip("\r") == word:
                    break
                body.append(lines[i - 1])
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


def flatten(command):
    """-> the command on one line: an unquoted newline becomes `;`, a comment
    and a backslash-newline go."""
    out = []
    quote = None
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(command[i + 1])
                i = i + 1
            elif c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "\\" and i + 1 < n:
            if command[i + 1] != "\n":
                out.append(c + command[i + 1])
            i = i + 1
        elif c == "\n":
            out.append(" ; ")
        elif c == "#" and (not out or out[-1][-1:] in (" ", "\t", ";")):
            while i + 1 < n and command[i + 1] != "\n":
                i = i + 1
        else:
            out.append(c)
        i = i + 1
    return "".join(out)


def segments(command):
    """-> ([[word]] one list per simple command, [heredoc bodies]).
    raises ValueError on a command the shell could not run either."""
    body, bodies = heredocs(command.replace("\r\n", "\n"))
    lex = shlex.shlex(flatten(body), posix=False, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    out, now = [], []
    for token in lex:
        if token in SEPARATORS or (set(token) <= set(";&|()")
                                   and ">" not in token):
            if now:
                out.append(now)
            now = []
        else:
            now.append(token)
    if now:
        out.append(now)
    return out, bodies


def bare(word):
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "'\"":
        return word[1:-1]
    return word


def program(words):
    """-> (its name, lowercased and without a path or .exe, its arguments)."""
    k = 0
    while k < len(words) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[k])
                              or bare(words[k]).lower() in WRAPPERS):
        k = k + 1
    if k >= len(words):
        return "", []
    name = os.path.basename(bare(words[k]).replace("\\", "/")).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name, words[k + 1:]


def is_sink(target, cwd):
    t = bare(target).strip()
    if t.lower() in SINKS or t.startswith("/dev/"):
        return True
    if ".." in re.split(r"[\\/]", t):
        return False
    if TEMP.match(t):
        return True
    full = os.path.normcase(os.path.abspath(os.path.join(cwd, t)))
    tmp = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
    tree = os.path.normcase(os.path.abspath(cwd))
    in_tree = full == tree or full.startswith(tree + os.sep)
    return not in_tree and (full == tmp or full.startswith(tmp + os.sep))


def cut(words, upto):
    return " ".join(words[:upto])


def is_redirect(token):
    return set(token) <= set("<>&|") and ("<" in token or ">" in token)


def writes_in(words, bodies, cwd):
    """-> the words of one simple command that write a file, or ""."""
    rest = []
    skip = False
    for j, t in enumerate(words):
        if skip:
            skip = False
            continue
        if not is_redirect(t):
            nxt = words[j + 1] if j + 1 < len(words) else ""
            if not (t.isdigit() and is_redirect(nxt)):
                rest.append(t)
            continue
        skip = True
        if ">" not in t:
            continue
        if j + 1 >= len(words):
            return cut(words, j + 1)
        target = words[j + 1]
        if t.endswith("&") and (target.isdigit() or target == "-"):
            continue
        if not is_sink(target, cwd):
            return cut(words, j + 2)
    name, args = program(rest)
    plain = [bare(a) for a in args]
    loose = [a for a in plain if not a.startswith("-")]
    if name in ("sed", "gsed") and any(
            a == "--in-place" or a.startswith("--in-place=")
            or re.match(r"^-[nrEsuzl]*i", a) for a in plain):
        return cut(words, 3)
    if name == "perl" and any(re.match(r"^-[aclnpsuUwWtTXv0-9]*i", a)
                              for a in plain):
        return cut(words, 3)
    if name == "tee" or name == "tee-object":
        if any(not is_sink(a, cwd) for a in loose):
            return cut(words, 3)
    if name in COPIERS:
        dest = None
        for k, a in enumerate(plain):
            if a in ("-t", "--target-directory", "-destination") \
                    and k + 1 < len(plain):
                dest = plain[k + 1]
            elif a.startswith("--target-directory="):
                dest = a.split("=", 1)[1]
        if dest is None and len(loose) >= 2:
            dest = loose[-1]
        if dest is not None and not is_sink(dest, cwd):
            return cut(words, len(words))
    if name in PS_WRITERS or name == "truncate":
        return cut(words, 3)
    if name == "dd" and any(a.startswith("of=") and not is_sink(a[3:], cwd)
                            for a in plain):
        return cut(words, 3)
    if any(NET_WRITE.search(w) for w in words):
        return cut(words, 3)
    if name.startswith("python") or name in ("py", "py3"):
        code = [plain[k + 1] for k, a in enumerate(plain)
                if a == "-c" and k + 1 < len(plain)]
        if not code and "<<" in words:
            code = list(bodies)
        if any(PY_WRITE.search(c) for c in code):
            return cut(words, 2) + " <code that writes a file>"
    return ""


def writes(command, cwd=None):
    """-> the part of a shell command that writes a file, "" when none does.
    raises ValueError when the command cannot be read."""
    cwd = cwd or os.getcwd()
    found, bodies = segments(command)
    for words in found:
        hit = writes_in(words, bodies, cwd)
        if hit:
            return hit
    return ""


def snippet(text, most=120):
    text = " ".join(text.split())
    return text if len(text) <= most else text[:most - 3] + "..."


def note(path, data, hit):
    if not path:
        return
    line = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
            "session": data.get("session_id"),
            "tool": data.get("tool_name"),
            "command": snippet((data.get("tool_input") or {}).get("command")
                               or "", 500),
            "refused": hit}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def arguments(argv):
    """-> (the denials file or None, [the files no tool may write])."""
    denials, kept = None, []
    i = 0
    while i < len(argv):
        if argv[i] == KEEP and i + 1 < len(argv):
            kept.append(argv[i + 1])
            i = i + 2
            continue
        if denials is None:
            denials = argv[i]
        i = i + 1
    return denials, kept


def full(p, cwd):
    return os.path.normcase(os.path.realpath(os.path.join(cwd, p)))


def same(path, other, cwd):
    return full(path, cwd) == full(other, cwd)


def inside(path, folder, cwd):
    top = full(folder.rstrip("/\\"), cwd)
    return full(path, cwd).startswith(top + os.sep)


def edited(data, kept):
    """-> (the path an edit tool call writes, the kept file or folder it
    falls under), ("", "") for a path none is."""
    given = data["tool_input"]
    path = given.get("file_path") or given.get("notebook_path")
    if not isinstance(path, str) or not path:
        raise TypeError("no file path")
    cwd = data.get("cwd") or os.getcwd()
    for k in kept:
        if k.endswith(("/", "\\")):
            if inside(path, k, cwd) and path.lower().endswith(".md"):
                return path, k
        elif same(path, k, cwd):
            return path, k
    return "", ""


def decide(argv, raw):
    """-> (exit code, what to print on stderr) for one PreToolUse call. 0 lets
    it run, 2 refuses it."""
    denials, kept = arguments(argv)
    try:
        data = json.loads(raw)
        tool = data.get("tool_name")
        if tool in EDITORS:
            hit, under = edited(data, kept) if kept else ("", "")
            said = KEPT_FACTS if under.endswith(("/", "\\")) else KEPT
        elif tool in TOOLS:
            command = data["tool_input"]["command"]
            if not isinstance(command, str):
                raise TypeError("the command is not text")
            hit = writes(command, data.get("cwd") or None)
            said = REASON
        else:
            return 0, ""
    except Exception as e:
        return 2, UNREAD.format(type(e).__name__)
    if not hit:
        return 0, ""
    try:
        note(denials, data, hit)
    except OSError:
        pass
    return 2, said.format(snippet(hit))


def denied(folder, sessions):
    """-> how many calls the hook refused in these sessions, from the run
    folder's denials file."""
    path = folder / FILE
    if not path.is_file():
        return 0
    n = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("session") in sessions:
            n = n + 1
    return n


# what a model says when it has just walked into one of the traps above
TRAPS = (
    re.compile(r"\b(sed|perl|awk|substitution|replacement|regex)\b[^\n]{0,60}?"
               r"\b(didn'?t|did not|doesn'?t|does not|failed to) match", re.I),
    re.compile(r"\bhere-?doc\b[^\n]{0,120}?(escape|backslash|newline|\\n)"
               r"|(escape|backslash|newline|\\n)[^\n]{0,120}?\bhere-?doc\b",
               re.I),
    re.compile(r"\bCRLF\b|\bline[- ]endings?\b", re.I),
)


def recovered(session):
    """-> how many of the model's messages in a session's transcript name a
    shell trap it walked into, None when there is no transcript to read."""
    from agentweft.runner.handoff import _text, projects

    if not session:
        return None
    try:
        found = sorted(projects().glob("*/" + session + ".jsonl"))
    except OSError:
        return None
    if not found:
        return None
    hit = set()
    raw = found[0].read_text(encoding="utf-8", errors="replace")
    for n, line in enumerate(raw.split("\n")):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        message = data.get("message") if isinstance(data, dict) else None
        if data.get("type") != "assistant" or not isinstance(message, dict):
            continue
        content = message.get("content")
        pieces = content if isinstance(content, list) else [content]
        said = "\n".join(_text(p.get("text", "")) if isinstance(p, dict)
                         else _text(p) for p in pieces
                         if not isinstance(p, dict) or p.get("type") == "text")
        if any(t.search(said) for t in TRAPS):
            hit.add(message.get("id") or n)
    return len(hit)


def main():
    code, said = decide(sys.argv[1:], sys.stdin.read())
    if said:
        sys.stderr.write(said + "\n")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.stderr.write(UNREAD.format("an error of its own") + "\n")
        sys.exit(2)
