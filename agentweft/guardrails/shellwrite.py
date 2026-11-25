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
writing (`tee`, `cp`, `sed -i`, ...), in each command, in each command a
`$(...)` or backquotes run, and in the command a shell is handed by `-c` or
by a heredoc (`bash -c '...'`, `sh <<EOF`). it reads quotes as the shell
does: a `\\"` inside double quotes, a `$'...'` and a quote inside a
substitution do not end a word, a `<<` inside quotes or an arithmetic
`$((...))` opens no heredoc, and operators written together (`;>`, `)>`)
are read one by one. a program that writes files as a side effect of
something else is not seen, and neither is a command `eval` builds or a
script file a shell runs. anything the hook cannot read, a quote left open, input that is not a
call or an error of its own, is refused too, and its line in the denials file
says `unread` with the error's kind: a check that crashes and lets the call
through is no check, and a refusal nobody can count is no record.

the same hook also stands on Write, Edit, MultiEdit and NotebookEdit for a
step that has them in a place: one granted `write` or `edit`, or one granted
nothing, which has every tool. it holds those tools to two things. each
`--place <path>` argument is the place the step works in, and a path outside
every one of them is refused, unless it is under the run's own `tmp/`, the
folder beside the denials file, where a step may keep a scratch file. the
fence compares the tree inside the place only, so a helper written beside it
would go unseen. each `--keep <path>` argument is a file no tool may write,
or a folder, ending in `/`, inside which no tool may write a `.md` file, and
the runner passes decisions.md and facts/ in the place (any other file there
is the project's own). a ruling there lets a change stand and a fact tells
the next step its way, so a step writing either would be ruling on its own
work (`guardrails/rulings.py` and `guardrails/factsguard.py` catch whatever
gets past). each `--keep-all <path>` is a path no tool may write, nor any
file under it: the runner passes the place's `.git`, whose config and hooks
git runs as the person (`guardrails/owngit.py`).

the module runs as a script, by path, in a process of its own, so nothing at
its top level may import from the package.
"""
import datetime
import json
import os
import posixpath
import re
import sys
import tempfile

FILE = "tool-denials.jsonl"

TOOLS = ("Bash", "PowerShell")
# MultiEdit is an older name the cli still maps onto Edit
EDITORS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
KEEP = "--keep"
KEEP_ALL = "--keep-all"
PLACE = "--place"
SCRATCH = "tmp"

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
KEPT_GIT = ("refused: `{0}` is in the place's `.git/`, which no step writes:"
            " its config and hooks run as the operator on the runner's next"
            " git. change the project's files; if the repo's git needs"
            " changing, say so on a NEEDS: line and stop.")
OUTSIDE = ("refused: `{0}` is outside the place this step works in, and"
           " nothing outside it is the step's to change. write the project's"
           " files inside the place{1}.")
SCRATCH_SAID = ", and a scratch file under `{0}`"
UNREAD = ("refused: the shell-write check could not read this call ({0}), so"
          " it is not let through. create or change files with the Write or"
          " Edit tool.")


def heredocs(command):
    """-> (the command with every heredoc body taken out, [the bodies])."""
    lines = command.split("\n")
    kept, bodies = [], []
    state = [None, 0]
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i = i + 1
        bare_at = open_at(line, state)
        for m in HEREDOC.finditer(line):
            if m.start() not in bare_at:
                continue
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


def open_at(line, state):
    """-> the indices of `line` that stand outside any quote, arithmetic
    `$((...))` or comment, where a `<<` opens a heredoc. `state`, [the
    open quote or None, the arithmetic's paren depth], carries a quote or
    an arithmetic across lines and is updated."""
    out = set()
    i, n = 0, len(line)
    while i < n:
        c, quote = line[i], state[0]
        if quote == "'":
            state[0] = None if c == "'" else quote
        elif quote in ('"', "$'"):
            if c == "\\":
                i = i + 1
            elif c == quote[-1]:
                state[0] = None
        elif c == "\\":
            i = i + 1
        elif c == "'" or c == '"':
            state[0] = c
        elif line.startswith("$'", i):
            state[0] = "$'"
            i = i + 1
        elif line.startswith("$((", i):
            state[1] = state[1] + 2
            i = i + 2
        elif state[1] and c in "()":
            state[1] = state[1] + (1 if c == "(" else -1)
        elif c == "#" and not state[1] and (i == 0 or line[i - 1] in
                                            " \t;&|("):
            break
        elif not state[1]:
            out.add(i)
        i = i + 1
    return out


PUNCTUATION = "();<>|&"
# longest first, so `;>` is a separator then a redirect, never one word
OPERATORS = ("&>>", "<<<", ";;", "&&", "||", "|&", ">>", ">|", "&>", ">&",
             "<&", "<<", "<>", "<(", ">(")
ARITH_WORDS = re.compile(r"[A-Za-z_]\w*\s+[A-Za-z_$]")


def arithmetic(inner):
    """whether the text inside a `$(...)` is an arithmetic `((...))`: the
    shell reads `$((x << 2))` as numbers, never as a command that writes.
    a body holding one word right after another (`cd a`) or a `;` is read
    as a command instead."""
    return inner.startswith("(") and inner.endswith(")") \
        and ";" not in inner and not ARITH_WORDS.search(inner)


def single_end(text, i):
    """-> the index of the `'` that closes a quote opened before `i`."""
    end = text.find("'", i)
    if end < 0:
        raise ValueError("no closing quotation")
    return end


def ansi_end(text, i):
    """-> the index of the `'` that closes a `$'...'`, where a backslash
    escapes the next character."""
    while i < len(text):
        if text[i] == "\\":
            i = i + 2
            continue
        if text[i] == "'":
            return i
        i = i + 1
    raise ValueError("no closing quotation")


def tick_end(text, i):
    while i < len(text):
        if text[i] == "\\":
            i = i + 2
            continue
        if text[i] == "`":
            return i
        i = i + 1
    raise ValueError("no closing backquote")


def double_end(text, i, inner):
    """-> the index of the `"` that closes a quote opened before `i`; each
    command substituted inside it joins `inner`."""
    while i < len(text):
        c = text[i]
        if c == "\\":
            i = i + 2
            continue
        if c == '"':
            return i
        if c == "$" and text[i + 1:i + 2] == "(":
            end = paren_end(text, i + 2)
            if not arithmetic(text[i + 2:end]):
                inner.append(text[i + 2:end])
            i = end + 1
            continue
        if c == "`":
            end = tick_end(text, i + 1)
            inner.append(text[i + 1:end])
            i = end + 1
            continue
        i = i + 1
    raise ValueError("no closing quotation")


def paren_end(text, i):
    """-> the index of the `)` that closes a `$(` opened before `i`."""
    depth = 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i = i + 2
            continue
        if c == "'":
            i = single_end(text, i + 1) + 1
            continue
        if c == "$" and text[i + 1:i + 2] == "'":
            i = ansi_end(text, i + 2) + 1
            continue
        if c == '"':
            i = double_end(text, i + 1, []) + 1
            continue
        if c == "`":
            i = tick_end(text, i + 1) + 1
            continue
        if c == "(":
            depth = depth + 1
        elif c == ")":
            depth = depth - 1
            if depth == 0:
                return i
        i = i + 1
    raise ValueError("no closing parenthesis")


def tokens(text, inner):
    """-> the words and operators of a command, each word with its quotes as
    written. an unquoted newline is `;`, a comment and a backslash-newline
    go, and each command substituted by `$(...)` or backquotes joins
    `inner`. raises ValueError on a quote or a substitution left open."""
    out, word = [], []

    def flush():
        if word:
            out.append("".join(word))
            del word[:]

    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t":
            flush()
            i = i + 1
        elif c == "\n":
            flush()
            out.append(";")
            i = i + 1
        elif c == "#" and not word:
            while i < n and text[i] != "\n":
                i = i + 1
        elif c == "\\":
            if text[i + 1:i + 2] != "\n":
                word.append(text[i:i + 2])
            i = i + 2
        elif c == "'":
            end = single_end(text, i + 1)
            word.append(text[i:end + 1])
            i = end + 1
        elif c == "$" and text[i + 1:i + 2] == "'":
            end = ansi_end(text, i + 2)
            word.append(text[i:end + 1])
            i = end + 1
        elif c == '"':
            end = double_end(text, i + 1, inner)
            word.append(text[i:end + 1])
            i = end + 1
        elif c == "$" and text[i + 1:i + 2] == "(":
            end = paren_end(text, i + 2)
            if not arithmetic(text[i + 2:end]):
                inner.append(text[i + 2:end])
            word.append(text[i:end + 1])
            i = end + 1
        elif c == "`":
            end = tick_end(text, i + 1)
            inner.append(text[i + 1:end])
            word.append(text[i:end + 1])
            i = end + 1
        elif c in PUNCTUATION:
            flush()
            op = next((o for o in OPERATORS if text.startswith(o, i)), c)
            out.append(op)
            i = i + len(op)
        else:
            word.append(c)
            i = i + 1
    flush()
    return out


def segments(command):
    """-> ([[word]] one list per simple command, those inside a `$(...)` or
    backquotes too, [heredoc bodies]). raises ValueError on a quote or a
    substitution left open, which the shell could not run either."""
    body, bodies = heredocs(command.replace("\r\n", "\n"))
    inner = []
    out, now = [], []
    for token in tokens(body, inner):
        if token in SEPARATORS or (set(token) <= set(";&|()")
                                   and ">" not in token):
            if now:
                out.append(now)
            now = []
        else:
            now.append(token)
    if now:
        out.append(now)
    for text in inner:
        more, found = segments(text)
        out = out + more
        bodies = bodies + found
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


def is_sink(target, cwd, scratch=None):
    t = bare(target).strip()
    if t.lower() in SINKS or t.startswith("/dev/"):
        return True
    if ".." in re.split(r"[\\/]", t):
        return False
    if TEMP.match(t):
        return True
    if scratch and not outside(t, scratch, cwd):
        return True
    # real paths: a temp folder reached through a link (macos's /var is one)
    # is named either way, by the model and by gettempdir
    full = os.path.normcase(os.path.realpath(os.path.join(cwd, t)))
    tmp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
    tree = os.path.normcase(os.path.realpath(cwd))
    in_tree = full == tree or full.startswith(tree + os.sep)
    return not in_tree and (full == tmp or full.startswith(tmp + os.sep))


def cut(words, upto):
    return " ".join(words[:upto])


def is_redirect(token):
    return set(token) <= set("<>&|") and ("<" in token or ">" in token)


def writes_in(words, bodies, cwd, scratch=None):
    """-> the words of one simple command that write a file, or ""."""
    def sink(target):
        return is_sink(target, cwd, scratch)

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
        if not sink(target):
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
        if any(not sink(a) for a in loose):
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
        if dest is not None and not sink(dest):
            return cut(words, len(words))
    if name in PS_WRITERS or name == "truncate":
        return cut(words, 3)
    if name == "dd" and any(a.startswith("of=") and not sink(a[3:])
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
    if name in SHELLS:
        code = [unquoted(args[k + 1]) for k, a in enumerate(plain)
                if SHELL_C.match(a) and k + 1 < len(args)]
        if not code and "<<" in words:
            code = list(bodies)
        for text in code:
            hit = writes(text, cwd, scratch)
            if hit:
                return hit
    return ""


SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SHELL_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


def unquoted(word):
    """-> one shell word as the program it is handed to receives it: its
    quotes taken off, each escape read."""
    out, i, n = [], 0, len(word)
    while i < n:
        c = word[i]
        if c == "'":
            end = single_end(word, i + 1)
            out.append(word[i + 1:end])
            i = end + 1
        elif word.startswith("$'", i):
            end = ansi_end(word, i + 2)
            out.append(word[i + 2:end])
            i = end + 1
        elif c == '"':
            end = double_end(word, i + 1, [])
            out.append(re.sub(r'\\([\\"$`\n])', r"\1", word[i + 1:end]))
            i = end + 1
        elif c == "\\":
            out.append(word[i + 1:i + 2])
            i = i + 2
        else:
            out.append(c)
            i = i + 1
    return "".join(out)


def writes(command, cwd=None, scratch=None):
    """-> the part of a shell command that writes a file, "" when none does.
    a write into `scratch`, the run's own tmp, is let through like one into
    the system's. raises ValueError when the command cannot be read."""
    cwd = cwd or os.getcwd()
    found, bodies = segments(command)
    for words in found:
        hit = writes_in(words, bodies, cwd, scratch)
        if hit:
            return hit
    return ""


def snippet(text, most=120):
    text = " ".join(text.split())
    return text if len(text) <= most else text[:most - 3] + "..."


def path_snippet(text, most=120):
    """`snippet` for a path, cut from the front: its end names the file."""
    text = " ".join(text.split())
    return text if len(text) <= most else "..." + text[-(most - 3):]


def note(path, data, hit, more=None):
    if not path:
        return
    data = data if isinstance(data, dict) else {}
    given = data.get("tool_input")
    given = given if isinstance(given, dict) else {}
    command = given.get("command")
    line = {"time": datetime.datetime.now().isoformat(timespec="seconds"),
            "session": data.get("session_id"),
            "tool": data.get("tool_name"),
            "command": snippet(command if isinstance(command, str) else "",
                               500),
            "refused": hit}
    line.update(more or {})
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def arguments(argv):
    """-> (the denials file or None, [the files no tool may write], [the
    place's spellings], [the paths no tool may write, nor anything under
    them])."""
    denials, kept, places, whole = None, [], [], []
    into = {KEEP: kept, PLACE: places, KEEP_ALL: whole}
    i = 0
    while i < len(argv):
        if argv[i] in into and i + 1 < len(argv):
            into[argv[i]].append(argv[i + 1])
            i = i + 2
            continue
        if denials is None:
            denials = argv[i]
        i = i + 1
    return denials, kept, places, whole


DRIVE = re.compile(r"^[A-Za-z]:/")
SHELL_DRIVE = re.compile(r"^/([A-Za-z])(?=/|$)")


def outside(path, place, base=None):
    """whether a path a tool writes is outside the place. a relative one is
    read from `base`, the place when none is given; either separator splits
    it. on a place with a drive letter, Git Bash's `/d/...` is read as that
    drive, and case does not tell two paths apart."""
    said = path.replace("\\", "/")
    if not said.startswith("/") and not DRIVE.match(said):
        said = str(base if base is not None else place).replace(
            "\\", "/").rstrip("/") + "/" + said
    whole = posixpath.normpath(said)
    for root in dict.fromkeys([str(place), os.path.realpath(str(place))]):
        top = posixpath.normpath(root.replace("\\", "/"))
        got = whole
        if DRIVE.match(top):
            got = SHELL_DRIVE.sub(r"\1:", got)
        if DRIVE.match(top) or DRIVE.match(got):
            top, got = top.casefold(), got.casefold()
        if got == top or got.startswith(top.rstrip("/") + "/"):
            return False
    return True


def scratch_of(denials):
    """-> the run's own tmp folder, beside its denials file, or None."""
    if not denials:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(denials)), SCRATCH)


def fenced(data, places, scratch):
    """-> the path an edit tool call writes outside every place and outside
    the run's tmp, "" for one inside."""
    given = data["tool_input"]
    path = given.get("file_path") or given.get("notebook_path")
    if not isinstance(path, str) or not path:
        raise TypeError("no file path")
    cwd = data.get("cwd") or places[0]
    roots = list(places) + ([scratch] if scratch else [])
    if all(outside(path, root, cwd) for root in roots):
        return path
    return ""


def full(p, cwd):
    """-> `p` as one comparable path. beside a working folder with a drive
    letter, Git Bash's `/d/...` is that drive, as `outside` reads it."""
    said = p
    if DRIVE.match(str(cwd).replace("\\", "/")):
        said = SHELL_DRIVE.sub(r"\1:", p.replace("\\", "/"))
    return os.path.normcase(os.path.realpath(os.path.join(cwd, said)))


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


def held(data, whole):
    """-> the path an edit tool call writes when it is one of `whole` or
    under one, "" for one that is neither."""
    given = data["tool_input"]
    path = given.get("file_path") or given.get("notebook_path")
    if not isinstance(path, str) or not path:
        raise TypeError("no file path")
    cwd = data.get("cwd") or os.getcwd()
    for top in whole:
        if same(path, top, cwd) or inside(path, top, cwd):
            return path
    return ""


def decide(argv, raw):
    """-> (exit code, what to print on stderr) for one PreToolUse call. 0 lets
    it run, 2 refuses it."""
    denials, kept, places, whole = arguments(argv)
    scratch = scratch_of(denials)
    more = None
    data = None
    try:
        data = json.loads(raw)
        tool = data.get("tool_name")
        if tool in EDITORS:
            hit = fenced(data, places, scratch) if places else ""
            if hit:
                more = {"path": hit, "outside": True}
                tail = SCRATCH_SAID.format(scratch.replace("\\", "/")) \
                    if scratch else ""
                said = OUTSIDE.format(path_snippet(hit), tail)
            else:
                hit = held(data, whole) if whole else ""
                said = KEPT_GIT.format(path_snippet(hit))
            if not hit:
                hit, under = edited(data, kept) if kept else ("", "")
                said = (KEPT_FACTS if under.endswith(("/", "\\"))
                        else KEPT).format(path_snippet(hit))
        elif tool in TOOLS:
            command = data["tool_input"]["command"]
            if not isinstance(command, str):
                raise TypeError("the command is not text")
            hit = writes(command, data.get("cwd") or None, scratch)
            said = REASON.format(snippet(hit))
        else:
            return 0, ""
    except Exception as e:
        try:
            note(denials, data, "", {"unread": type(e).__name__})
        except Exception:
            pass
        return 2, UNREAD.format(type(e).__name__)
    if not hit:
        return 0, ""
    try:
        note(denials, data, hit, more)
    except OSError:
        pass
    return 2, said


def refusals(folder, sessions):
    """-> every line of the run folder's denials file from these sessions."""
    path = folder / FILE
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("session") in sessions:
            out.append(data)
    return out


def denied(folder, sessions):
    """-> how many calls the hook refused in these sessions, from the run
    folder's denials file."""
    return len(refusals(folder, sessions))


def refused_outside(folder, sessions):
    """-> the paths the hook refused in these sessions as outside the
    place, in order."""
    return [str(d.get("path")) for d in refusals(folder, sessions)
            if d.get("outside") is True]


def outside_said(paths):
    """-> the step's why line for writes refused outside the place."""
    more = len(paths) - 1
    return ("the cli refused a write outside the place: " + paths[0]
            + (" (and " + str(more) + " more)" if more else ""))


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
