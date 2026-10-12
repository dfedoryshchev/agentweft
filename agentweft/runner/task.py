"""the task a run is pointed at, given when it is started.

one flow, many tasks: `--task "<text>"` or `--task-file <path>` instead of a
copy of the flow folder per bug with the bug written into worker.md.

a flow says where a task goes by writing {TASK} in its own words: a step's
prompt file, which hands it to that step, or instructions.md, which every step
is sent. it goes there and nowhere else, so a fanned-out flow that names it in
planner.md hands it to the planner, and the workers get the planner's plan the
way they always did.

a flow with nowhere to put a task refuses one, and a flow with a place refuses
to start without one: a worker told "here is a bug" with no bug in it answers
anyway.
"""
from pathlib import Path

from agentweft.flow.spec import step_id

MARK = "{TASK}"
FILE = "task.md"
FLAGS = ("--task", "--task-file")


def given(argv):
    """-> the task argv names, or None when it names none.

    ValueError, with the sentence to print, when it names one wrongly.
    """
    named = [f for f in FLAGS if f in argv]
    if len(named) > 1:
        raise ValueError("--task and --task-file are two answers to one "
                         "question. give one")
    if not named:
        return None
    flag = named[0]
    i = argv.index(flag)
    if len(argv) <= i + 1:
        raise ValueError(flag + " needs "
                         + ("the task" if flag == "--task" else "a file"))
    text = argv[i + 1]
    if flag == "--task-file":
        text = read(text)
    if not text.strip():
        raise ValueError(flag + " is empty. a run pointed at nothing has "
                         "nothing to do")
    return text


def read(name):
    path = Path(name)
    if not path.is_file():
        raise ValueError("--task-file " + name + ": no such file")
    try:
        # -sig: a file saved from Notepad starts with a BOM, and the model
        # would get it as the first character of the task
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("--task-file " + name + " is not UTF-8. save it as "
                         "UTF-8 and run again")


def places(flow_dir, fm):
    """-> the flow's own files that say where a task goes, in flow order.

    only the flow's files count. the role library is shared by every flow, so
    a {TASK} there would be a place in all of them at once.
    """
    out = []
    for name in ["instructions.md"] + [step_id(s) for s in fm.steps]:
        path = flow_dir / name
        if name in out or not path.is_file():
            continue
        if MARK in path.read_text(encoding="utf-8"):
            out.append(name)
    return out


def settle(flow, where, asked, started_on=None, pick_up=None):
    """-> the task this run works on, or None for a flow that takes none.

    `asked` is what the command line said and `started_on` what the run being
    picked up was started with. ValueError, with the sentence to print, when
    the run cannot start on what it was given.
    """
    if started_on is not None and asked is not None and asked != started_on:
        raise ValueError(pick_up + " was started on another task. a resumed "
                         "run carries on with the one it started with, so "
                         "leave --task off")
    text = started_on if started_on is not None else asked
    if text is not None and not where:
        raise ValueError(flow + " has no place for a task. a flow takes one "
                         "by writing " + MARK + " where it should go: in "
                         "instructions.md for every step, or in one step's "
                         "own file for that step")
    if text is None and where:
        raise ValueError(flow + " takes a task (" + MARK + " in "
                         + ", ".join(where) + "). give it with --task "
                         "\"<text>\" or --task-file <path>")
    return text


def save(folder, text):
    """bytes, not text mode: on Windows text mode turns every newline into
    two, and the file would no longer be the task that was given."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_bytes(text.encode("utf-8"))


def saved(folder):
    """-> the task a run folder was started on, or None when it had none."""
    path = folder / FILE
    if not path.is_file():
        return None
    return path.read_bytes().decode("utf-8")
