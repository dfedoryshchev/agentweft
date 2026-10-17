"""`agentweft init`: the few choices a first run needs, written to `.env`.

the first run on someone else's machine needed a claude settings file nobody
had written down, and the attribution trailer landed on their commits. so the
choices are asked once, each with the answer the runner would have used anyway
as its default, and written where `load_env` already reads: the model per tier
as `MODEL_<TIER>`, the rest as `AGENTWEFT_<KEY>` (`settings.py`).
"""
import shutil
import sys
from pathlib import Path

from . import settings
from ..flow.spec import COMMITS

FILE = ".env"

PROVIDERS = ("cli", "api")
# `claude --permission-mode`'s choices, as `claude --help` lists them
PERMISSION_MODES = ("dontAsk", "acceptEdits", "auto", "bypassPermissions",
                    "manual", "plan")
YES = ("y", "yes")
NO = ("n", "no")


class Question(object):
    __slots__ = ("name", "text", "default", "choices", "kind", "note")

    def __init__(self, name, text, default, choices=None, kind="text",
                 note=""):
        self.name = name
        self.text = text
        self.default = default
        self.choices = choices
        self.kind = kind
        self.note = note

    def shown(self):
        out = self.text
        if self.choices:
            out += " (" + ", ".join(self.choices) + ")"
        if self.kind == "bool":
            return out + (" [Y/n]: " if self.default == "true" else " [y/N]: ")
        return out + " [" + self.default + "]: "

    def read(self, said):
        """-> the value to write, or None when `said` is not an answer."""
        said = said.strip()
        if not said:
            return self.default
        if self.kind == "bool":
            if said.lower() in YES:
                return "true"
            if said.lower() in NO:
                return "false"
            return None
        if self.kind == "count":
            return said if said.isdigit() else None
        if self.kind == "globs":
            return ",".join(g.strip() for g in said.split(",") if g.strip())
        if self.choices and said not in self.choices:
            return None
        return said

    def ask(self):
        if self.note:
            print(self.note)
        while True:
            value = self.read(input(self.shown()))
            if value is not None:
                return value
            if self.kind == "bool":
                print("  y or n")
            elif self.kind == "count":
                print("  a whole number, 0 for no cap")
            else:
                print("  one of: " + ", ".join(self.choices))


def env(key):
    return settings.env_name(key)


def text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return ",".join(value)
    return str(value)


def default(key):
    return text(settings.DEFAULTS[key])


QUESTIONS = (
    Question(env("provider"), "the provider a flow that names none runs on",
             default("provider"), PROVIDERS,
             note="cli shells out to `claude`; api is the http one, and reads "
                  "API_KEY, API_URL and MODEL"),
    Question("MODEL_HIGH", "the model a `high` step asks for", "",
             note="a model per tier: an alias such as opus or sonnet, or a "
                  "full id. blank leaves it to MODEL, then to the provider"),
    Question("MODEL_MID", "the model a `mid` step asks for", ""),
    Question("MODEL_LOW", "the model a `low` step asks for", ""),
    Question(env("permission_mode"), "the permission mode a step with a tool "
             "grant runs claude in", default("permission_mode"),
             PERMISSION_MODES,
             note="dontAsk denies anything the step's grant did not allow"),
    Question(env("co_author"), "keep the attribution trailer claude adds",
             default("co_author"), kind="bool"),
    Question(env("max_calls"), "calls a run may make before it parks",
             default("max_calls"), kind="count"),
    Question(env("max_tokens"), "tokens a run may spend before it parks, "
             "0 for no cap", default("max_tokens"), kind="count"),
    Question(env("tests_e2e"), "may coding flows write end-to-end tests",
             default("tests_e2e"), kind="bool",
             note="recommended: no. they are slow and want a running "
                  "system; say yes only if this project has one to test"),
    Question(env("commits"), "what a run commits", "none", COMMITS,
             note="none leaves every change in the work tree, wip commits "
                  "after each step, squash makes one commit per task"),
    Question(env("spec_globs"), "the files that are the spec, as globs "
             "from the top of the project, comma separated",
             default("spec_globs"), kind="globs"),
)

PRICES = Question("prices", "keep a price table of your own here "
                  "(prices.yaml)", "false", kind="bool")


def found(folder, flow):
    """-> `folder` as a path to type when it holds `flow`, or "" when there
    is none: `pip install .` does not carry it, a clone does."""
    if (Path(folder) / flow / "flow.yaml").is_file():
        return folder
    beside = Path(__file__).resolve().parents[2] / folder
    if (beside / flow / "flow.yaml").is_file():
        return str(beside)
    return ""


def quoted(path):
    return '"' + path + '"' if " " in path else path


def quick_start():
    where = found("examples", "minimal")
    out = ["", "the quick start, from here:", ""]
    if where:
        out.append("    agentweft minimal --force --flows " + quoted(where))
    else:
        out.append("    agentweft minimal --force --flows examples"
                   "    (from a clone of agentweft)")
    real = ('    agentweft fix-with-test --workdir <your project> '
            '--task "<the bug, in one line>"')
    flows = found("flows", "fix-with-test")
    if flows == "flows":
        out.append(real)
    elif flows:
        out.append(real + " --flows " + quoted(flows))
    else:
        out.append(real + "    (from a clone of agentweft)")
    out += ["", "the first runs on the fake provider and costs nothing. the "
            "second is a real run;", "`docs/quickstart.md` walks both."]
    return out


def kept(path, owned):
    """-> the lines of an existing file that are not one of `owned`'s keys, so
    `--force` rewrites the answers and leaves a key of yours alone."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if line.strip().startswith("#") or key not in owned:
            out.append(line)
    return out


def cmd_init():
    """python run.py init [--yes] [--force]"""
    yes = "--yes" in sys.argv
    force = "--force" in sys.argv
    path = Path(FILE)
    if path.exists() and not force:
        print(FILE + " is already here, and init does not write over it."
              " `agentweft init --force` rewrites the keys init asks about and"
              " leaves the rest")
        return 1
    answers = [(q.name, q.default if yes else q.ask()) for q in QUESTIONS]
    prices = PRICES.default if yes else PRICES.ask()
    owned = [name for name, _ in answers]
    lines = ["# written by agentweft init. `agentweft init --force` asks again"]
    lines += [l for l in kept(path, owned) if not l.startswith("# written by")]
    lines += [name + "=" + value for name, value in answers if value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote " + FILE)
    if prices == "true":
        from agentweft.guardrails import prices as table

        own = Path("prices.yaml")
        if own.exists():
            print("prices.yaml is already here, left as it is")
        else:
            shutil.copyfile(table.SHIPPED, own)
            print("wrote prices.yaml, a copy of the shipped table to edit")
    for line in quick_start():
        print(line)
    return 0
