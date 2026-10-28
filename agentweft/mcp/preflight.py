"""do not let a step walk into the blast radius without saying so.

the risk map has been advisory since june: it goes into the planner's prompt
and the planner mostly weights by it. mostly is the problem. a plan that says
"rewrite the thing everything imports" is exactly the plan a model produces
when it is being helpful, and nothing downstream stops it.

so: before a step that is going to touch files, check what it is about to touch
against the ranking. above the threshold it is flagged, and the flow can be set
to refuse rather than flag, or to park the run so a person makes the edit.

this is the half of the idea that is not a prompt. a prompt asking an agent to
be careful about a hot file is a prompt. this is a number and a comparison.

the runner asks twice. once on the text a step is handed, before the step is
called, because a step that can edit files has already edited them by the time
its answer comes back. and once on what the step said it did, after. the first
catches only the files the plan names: a file the model picks mid-step is not
in the text it was handed, so the second check, and the fence on what actually
changed, are still what report it.
"""
import re

DEFAULT_THRESHOLD = 0.7
NO_RANKING = "no ranking to check against"


def parse_ranking(text):
    """`path score` per line, which is what every ranking i have seen emits.
    anything it cannot parse is skipped rather than guessed at. the path is
    all of the line before its score, a space in it included."""
    out = {}
    for line in (text or "").split(chr(10)):
        parts = line.strip().rsplit(None, 1)
        if len(parts) < 2:
            continue
        try:
            out[parts[0].strip().rstrip(":")] = float(parts[-1])
        except ValueError:
            continue
    return out


def files_mentioned(text):
    """paths a step says it is going to touch. crude on purpose - it is looking
    for something to check, not parsing a patch."""
    found = set()
    for m in re.finditer(r"[\w./\\-]+\.[A-Za-z]{1,5}\b", text or ""):
        token = re.sub(r"^(\.\.?/)+", "", _slashes(m.group(0)).rstrip("."))
        if "." in token and not token.startswith("."):
            found.add(token)
    return found


def _slashes(path):
    return path.replace(chr(92), "/")


def _same_file(a, b):
    """one path is the other, or ends with it at a `/`."""
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def check(text, ranking_text, threshold=DEFAULT_THRESHOLD):
    """-> list of (path, score) at or above the threshold, or None when there
    is no ranking to check against.

    None and [] are different answers on purpose. [] is "checked, nothing
    hot"; None is "not checked", which a step set to park or refuse must not
    read as permission to go on."""
    ranking = parse_ranking(ranking_text)
    if not ranking:
        return None
    hot = []
    for path in files_mentioned(text):
        for known, score in ranking.items():
            if _same_file(_slashes(known), path):
                if score >= threshold:
                    hot.append((known, score))
                break
    return sorted(set(hot), key=lambda p: -p[1])


SMALL = "small"
NOT_SMALL = "not small"
# past these a change is not small, whatever it touches: logic lines added
# or taken out in code, code files, and new public names
SMALL_LINES = 20
SMALL_FILES = 2
SMALL_NAMES = 1
LOCALE_DIRS = ("locale", "locales", "i18n", "l10n", "translations", "lang",
               "langs")
LOCALE_SUFFIXES = (".po", ".pot", ".ftl", ".xliff", ".xlf", ".strings",
                   ".arb", ".resx")
DATA_DIRS = ("data", "fixtures", "samples", "assets", "static")
DATA_SUFFIXES = (".csv", ".tsv", ".jsonl", ".ndjson", ".svg", ".png", ".jpg",
                 ".gif", ".ico", ".txt")
DOC_SUFFIXES = (".md", ".rst", ".adoc")
CONFIG_SUFFIXES = (".toml", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".json",
                   ".env", ".properties")
CONFIG_NAMES = ("settings.py", "config.py", "conftest.py", "setup.py",
                "dockerfile", "makefile", ".env")
# what the code installs and builds with: a changed line here reaches every
# file, so it is config whose every line counts, set key or not
MANIFEST = re.compile(r"^(?:requirements[\w.-]*\.(?:txt|in)|constraints[\w.-]*"
                      r"\.txt|pyproject\.toml|setup\.cfg|pipfile|package\.json"
                      r"|pnpm-lock\.yaml|go\.mod|go\.sum|gemfile|cargo\.toml"
                      r"|[\w.-]+\.lock|package-lock\.json|(?:gnu)?makefile"
                      r"|(?:docker|container)file(?:\.[\w.-]+)?"
                      r"|[\w.-]+\.dockerfile)$")
# a line that sets a key in a config file, not a comment or a header
CONFIG_KEY = re.compile(r"^\s*[\"']?[\w.\-]+[\"']?\s*[:=]")
NEW_NAME = re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z]\w*)")
FLAG = re.compile(r"""add_argument\(\s*["']--?[\w-]+|add_option\(|"""
                  r"""@click\.option\(|typer\.Option\(""")


def file_kind(path):
    """-> code, test, config, locale, data or docs, by where the file is and
    what it is called. a big file of a low-logic kind holds little to review;
    a small change to a config file reaches everything that reads it."""
    from agentweft.guardrails.snapshot import is_test

    path = _slashes(path)
    parts = [p.lower() for p in path.split("/")]
    name = parts[-1]
    dot = name.rfind(".")
    suffix = name[dot:] if dot > 0 else ""
    if is_test(path):
        return "test"
    if suffix in LOCALE_SUFFIXES or any(p in LOCALE_DIRS for p in parts[:-1]):
        return "locale"
    if suffix in DOC_SUFFIXES or parts[0] == "docs":
        return "docs"
    if manifest(path):
        return "config"
    if suffix in DATA_SUFFIXES or (suffix in CONFIG_SUFFIXES and any(
            p in DATA_DIRS for p in parts[:-1])):
        return "data"
    if suffix in CONFIG_SUFFIXES or name in CONFIG_NAMES:
        return "config"
    return "code"


def manifest(path):
    """whether `path` is a dependency or build manifest, outside a data
    folder."""
    parts = [p.lower() for p in _slashes(path).split("/")]
    return bool(MANIFEST.match(parts[-1])) and not any(
        p in DATA_DIRS for p in parts[:-1])


def size(files, ranking_text=None, threshold=DEFAULT_THRESHOLD):
    """-> how big and how risky a change is, from the files it changed:
    [(path, the lines it added, how many it took out)], a deleted file with
    every line taken out, None when the change could not be read. `blast` is
    high when it touches a file the risk map ranks at or above `threshold`,
    sets a key in a config file, changes a dependency manifest, or adds a
    command-line flag; with no risk map to read it is `unknown`, never low.
    `logic_lines` counts only code, never tests, docs, data or locale
    files. a change is `small` only with a low blast, few logic lines, few
    code files and at most one new public name. `why` says what decided it,
    one reason a line."""
    out = {"size": NOT_SMALL, "blast": "low", "logic": "logic",
           "logic_lines": 0, "files": 0, "why": [], "read": files is not None}
    if files is None:
        out["why"].append("the change could not be read")
        return out
    ranking = parse_ranking(ranking_text)
    code, names = [], []
    for path, added, removed in files:
        kind = file_kind(path)
        out["files"] += 1
        for known, score in ranking.items():
            if _same_file(_slashes(known), _slashes(path)) \
                    and score >= threshold:
                out["blast"] = "high"
                out["why"].append(path + " is ranked " + str(score)
                                  + " on the risk map")
        if kind == "config" and manifest(path) and (added or removed):
            out["blast"] = "high"
            out["why"].append(path + " changes a dependency manifest")
        elif kind == "config" and any(CONFIG_KEY.match(l) for l in added):
            out["blast"] = "high"
            out["why"].append(path + " sets a key in a config file")
        if kind != "code":
            continue
        code.append(path)
        out["logic_lines"] += len([l for l in added if l.strip()]) + removed
        if any(FLAG.search(l) for l in added):
            out["blast"] = "high"
            out["why"].append(path + " adds a command-line flag")
        names.extend(m.group(1) for m in (NEW_NAME.match(l) for l in added)
                     if m and not m.group(1).startswith("_"))
    if not ranking and out["blast"] != "high":
        out["blast"] = "unknown"
        out["why"].append("no risk map to rank the files against, so the"
                          " blast radius is unknown")
    if not out["logic_lines"]:
        out["logic"] = "low-logic"
    if out["logic_lines"] > SMALL_LINES:
        out["why"].append(str(out["logic_lines"]) + " logic lines, more than "
                          + str(SMALL_LINES))
    if len(code) > SMALL_FILES:
        out["why"].append(str(len(code)) + " code files, more than "
                          + str(SMALL_FILES))
    if len(names) > SMALL_NAMES:
        out["why"].append(str(len(names)) + " new public names: "
                          + ", ".join(names))
    if not out["why"]:
        out["size"] = SMALL
        out["why"].append(str(out["logic_lines"]) + " logic line"
                          + ("" if out["logic_lines"] == 1 else "s") + " in "
                          + str(len(code)) + " code file"
                          + ("" if len(code) == 1 else "s") + ", nothing the"
                          " risk map ranks hot, no config key or flag")
    return out


def size_line(sized):
    """-> the size as one line for the record."""
    if not sized.get("read", True):
        return "not sized, so every reviewer runs: " + "; ".join(sized["why"])
    return (sized["size"] + ", " + sized["blast"] + " blast, "
            + sized["logic"] + ": " + "; ".join(sized["why"]))


def as_warning(hot):
    if not hot:
        return ""
    lines = ["", "this touches code the map says is risky:"]
    for path, score in hot:
        lines.append("- " + path + " (" + str(score) + ")")
    lines.append("say why it has to be this file, or propose a smaller change.")
    return chr(10).join(lines) + chr(10)
