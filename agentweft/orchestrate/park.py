"""stopping on purpose, and leaving behind something a person can act on.

the phase file has had a word for this since it came over: `gate: user`, the
point where the whole thing stops and it is my turn. nothing did it. the runner
could only stop by failing, so the two ways a run ends without finishing - it
broke, or it is waiting for me - looked the same in the journal and left the
same thing on disk, which is to say nothing i could act on.

this is the mechanism, and it is deliberately not the phase side's. no phase is
executed here either and this module has never heard of one. it takes what a
run knows - where it got to, what is left, who it waits for - and writes the
file the person being waited for has to read. the runner is what calls it.

the runner already has a Handoff and that is a different thing: what one step
passes to the next, machine to machine. this is what a run passes to a person.
"""
from pathlib import Path

FILE = "handoff.md"


def lines(run_id, flow, step, who, done, left, command):
    """the handoff as the lines it is written from.

    it answers four questions in the order a person asks them: what ran, where
    it stopped, why it stopped, and what to do about it. the last one is a
    command to type, not a description of one.
    """
    out = ["# parked: " + run_id, ""]
    out.append("waiting for    " + who)
    out.append("flow           " + flow)
    out.append("stopped after  " + step)
    out.append("")
    out.append("nothing failed. " + step + " finished and its checks passed. the flow")
    out.append("asks for " + who + " here, so the rest of it has not run.")
    out.append("")
    out.append("ran")
    for name, seconds in done:
        out.append("  " + name.ljust(16) + str(seconds) + "s")
    out.append("")
    out.append("left")
    for name in left or ["nothing"]:
        out.append("  " + name)
    out.append("")
    out.append("what " + step + " produced is in runs/" + run_id + "/" + step)
    out.append("read it before carrying on. that file is what the next step gets handed,")
    out.append("so editing it is how you change what the rest of the run works from.")
    out.append("")
    out.append("to carry on")
    out.append("  " + command)
    return out


def write(run_id, flow, step, who, done, left, command, runs=None):
    """write the handoff beside the step outputs, and hand back the path.

    the same folder as trace.md and gates.md. everything one run left behind
    stays in one place, and the person being waited for gets one path to look
    at rather than a mechanism of its own to learn.
    """
    folder = (runs or Path("runs")) / run_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / FILE
    body = lines(run_id, flow, step, who, done, left, command)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path
