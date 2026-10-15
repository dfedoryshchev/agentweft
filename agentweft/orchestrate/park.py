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


def lines(step, who, done, left, command, why=None, again=False, cause=None,
          handed=None, question=None):
    """the section as the lines it is written from.

    it answers four questions in the order a person asks them: what ran, where
    it stopped, why it stopped, and what to do about it. the last one is a
    command to type, not a description of one. `why` is for a stop the flow
    did not ask for. `again` is a step that produced nothing, so carrying on
    runs it again rather than handing on what it made. `handed` names the step
    whose output `step` was handed when the run parked before `step` ran.

    `who` is None for a run that stopped without waiting for anyone - a gate,
    the cap, a crash. it gets the same section under its `cause`: the step it
    stopped at runs again when it is carried on.

    `question` is what `step` asked instead of doing the work. the answer is
    given on the command line, not by editing a file, so the section ends
    with the command that takes it.
    """
    if question is not None:
        return ruling(step, who, done, left, command, question)
    if who is None:
        return stopped(step, cause, done, left, command, why)
    out = ["waiting for    " + who]
    if handed:
        out.append("stopped before " + step)
    else:
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
    if handed:
        out.append(step + " has not run. it was handed what " + handed + " produced, and")
        out.append("carrying on runs it on that: the go-ahead for the files named above.")
        out.append("edit what " + handed + " produced first to change what it works from.")
    elif again:
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


ANSWER = ' --answer "<your ruling>"'


def ruling(step, who, done, left, command, question):
    out = ["waiting for    " + who, "stopped at     " + step, ""]
    out.append(step + " asked for a ruling instead of doing the work:")
    out.append("")
    out.extend("  " + line for line in question.strip().split("\n"))
    out.append("")
    out.append("so the rest of it has not run.")
    out.append("")
    ran_and_left(out, done, left)
    out.append(step + " runs again with your answer at the end of its prompt, and")
    out.append("the question and the answer go into decisions.md. a longer answer")
    out.append("can come from a file: --answer-file <path>.")
    out.append("")
    out.append("to carry on")
    out.append("  " + command + ANSWER)
    return out


def refused(step, cite, done):
    """the section for a step that declined the work and cited the spec line
    that says why. nothing is owed: the run ends on it."""
    out = ["refused at     " + step, ""]
    out.append(step + " declined the work, citing:")
    out.append("  " + cite)
    out.append("")
    out.append("nothing failed. the run ends here, and that is its answer. to have")
    out.append("the work done anyway, change that line or start a new run whose")
    out.append("task says to.")
    out.append("")
    out.append("ran")
    for name, seconds in done:
        out.append("  " + name.ljust(16) + str(seconds) + "s")
    return out


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
