"""the goal a run serves, given beside the task when it is started.

`--goal "<text>"` or `--goal-file <path>` says what problem the run solves,
the why beside the spec's what. it is kept apart from the task and from
every spec file (`runs/<id>/goal.md`), so no step can cite a goal sentence
as a spec line: a CONFLICT, a WRONG TEST or a spec mark reads the spec as
the run found it, and the goal is not in it.

with a goal, every step's prompt ends its own words with it and asks the
step to name the part of its work that drives it and the one thing it was
handed that it doubts most; the handoff carries it beside the task. with
none, nothing is added anywhere: the prompts are what they were.
"""
from pathlib import Path

FILE = "goal.md"
FLAGS = ("--goal", "--goal-file")


def given(argv):
    """-> the goal argv names, or None when it names none or an empty one.

    ValueError, with the sentence to print, when it names one wrongly."""
    named = [f for f in FLAGS if f in argv]
    if len(named) > 1:
        raise ValueError("--goal and --goal-file are two answers to one"
                         " question. give one")
    if not named:
        return None
    flag = named[0]
    i = argv.index(flag)
    if len(argv) <= i + 1:
        raise ValueError(flag + " needs "
                         + ("the goal" if flag == "--goal" else "a file"))
    text = argv[i + 1]
    if flag == "--goal-file":
        path = Path(text)
        if not path.is_file():
            raise ValueError("--goal-file " + text + ": no such file")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("--goal-file " + text + " is not UTF-8. save it"
                             " as UTF-8 and run again")
    return text if text.strip() else None


def settle(asked, started_on, pick_up):
    """-> the goal this run serves: the one the run being picked up was
    started with, else the one given. ValueError when a resume is given
    another."""
    if started_on is not None and asked is not None and \
            asked.strip() != started_on.strip():
        raise ValueError(pick_up + " was started with another goal. a resumed"
                         " run carries on with the one it started with, so"
                         " leave --goal off")
    return started_on if started_on is not None else asked


def save(folder, text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_bytes(text.encode("utf-8"))


def saved(folder):
    """-> the goal a run folder was started with, or None."""
    path = folder / FILE
    if not path.is_file():
        return None
    text = path.read_bytes().decode("utf-8")
    return text if text.strip() else None


def fragment(text):
    """-> what a step's prompt ends its own words with when the run has a
    goal, "" when it has none."""
    if not text:
        return ""
    return ("\n\nTHE GOAL. the problem this run solves, as the operator gave"
            " it beside the task. it is no spec line: cite the spec and the"
            " request, never this.\n\n" + text.strip() + "\n\nbefore you"
            " start, name the part of your work that drives it, and the one"
            " thing you were handed that you doubt most.\n")


def first_line(text):
    return (text or "").strip().split("\n")[0]
