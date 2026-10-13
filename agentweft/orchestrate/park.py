"""stopping on purpose, and leaving behind something a person can act on.

the phase file has had a word for this since it came over: `gate: user`, the
point where the whole thing stops and it is my turn. nothing did it. the runner
could only stop by failing, so the two ways a run ends without finishing - it
broke, or it is waiting for me - looked the same in the journal and left the
same thing on disk, which is to say nothing i could act on.

this is the mechanism, and it is deliberately not the phase side's. no phase is
executed here either and this module has never heard of one. it takes what a
run knows - where it got to, what is left, who it waits for - and writes the
section the person being waited for has to read. the runner is what calls it,
and `runner/summary.py` is what writes the file it goes into: every run ends
with one handoff.md, and this is its "needs you" section when the run stopped
short, waiting for someone or not.

the runner already has a Handoff and that is a different thing: what one step
passes to the next, machine to machine. this is what a run passes to a person.
"""


def lines(step, who, done, left, command, why=None, again=False, cause=None):
    """the section as the lines it is written from.

    it answers four questions in the order a person asks them: what ran, where
    it stopped, why it stopped, and what to do about it. the last one is a
    command to type, not a description of one. `why` is for a stop the flow
    did not ask for. `again` is a step that produced nothing, so carrying on
    runs it again rather than handing on what it made.

    `who` is None for a run that stopped without waiting for anyone - a gate,
    the cap, a crash. it gets the same section under its `cause`: the step it
    stopped at runs again when it is carried on.
    """
    if who is None:
        return stopped(step, cause, done, left, command, why)
    out = ["waiting for    " + who]
    out.append(("stopped at     " if again else "stopped after  ") + step)
    out.append("")
    if why:
        out.append(why)
        out.append("so the rest of it has not run.")
    else:
        out.append("nothing failed. " + step + " finished and its checks passed. the flow")
        out.append("asks for " + who + " here, so the rest of it has not run.")
    out.append("")
    ran_and_left(out, done, left)
    if again:
        out.append(step + " produced nothing, so it runs again when you carry on.")
    else:
        out.append("what " + step + " produced is beside this file, as " + step + ".")
        out.append("read it before carrying on. that file is what the next step gets handed,")
        out.append("so editing it is how you change what the rest of the run works from.")
    out.append("")
    out.append("to carry on")
    out.append("  " + command)
    return out


def ran_and_left(out, done, left):
    out.append("ran")
    for name, seconds in done:
        out.append("  " + name.ljust(16) + str(seconds) + "s")
    out.append("")
    out.append("left")
    for name in left or ["nothing"]:
        out.append("  " + name)
    out.append("")


def stopped(step, cause, done, left, command, why):
    out = ["cause          " + str(cause)]
    out.append("stopped at     " + step)
    out.append("")
    if why:
        out.append(why)
    out.append("so the rest of it has not run.")
    out.append("")
    ran_and_left(out, done, left)
    out.append(step + " runs again when you carry on; the steps before it do not.")
    out.append("")
    out.append("to carry on")
    out.append("  " + command)
    return out
