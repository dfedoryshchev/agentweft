"""what the investigator found, carried to the steps after it.

its answer is labelled lines (`roles/library/investigator.md`), and the steps
after it are handed those lines and nothing else. an excerpt pasted under them
is the investigator's reading of the code standing in for the code, and the
next step can open the file. RELATED and DECISIONS are for the person who
started the run, so they go to its output and never to the fix: what the run
fixes is still the task it was given.
"""
import re

from agentweft.flow.spec import INVESTIGATOR, investigating, step_id
from agentweft.roles import resolver

from .manifest import NOT_RUN

STEP = INVESTIGATOR + ".md"
LABELS = ("RULED OUT", "DECISIONS", "RELATED", "ROOTED", "CAUSE", "SITES",
          "FEEDS", "REPRO", "TESTS")
HANDED = ("CAUSE", "SITES", "FEEDS", "TESTS", "RULED OUT", "REPRO")
FOR_THE_PERSON = ("RELATED", "DECISIONS")
LABEL = re.compile(r"^(" + "|".join(LABELS) + r"):(.*)$")

SCOPE = "{SCOPE}"
REACHED = "do not touch anything the test does not reach"
NAMED = ("touch the named sites only, every one of them and nothing else. a "
         "named site no test reaches is still fixed, and said on its own line "
         "after TEST: as `NOT REACHED: <file>:<function>`")


AUTO = "auto"
RED = "red-test"
NAMES_A_CAUSE = re.compile(r"\bcause\b", re.I)


def on(fm):
    return investigating(fm.raw) != "off"


def held(fm, order, kept=None):
    """-> the steps a run starts from: `order` without the cause step while
    `auto` has not switched it on.

    `kept` is the manifest of the run being picked up. a cause step that ran
    there, whatever it came to, is the run's own and stays in.
    """
    if investigating(fm.raw) != AUTO:
        return order
    if kept is not None and (kept.step(STEP) or {}).get("state") not in (
            None, NOT_RUN):
        return order
    return [s for s in order if s != STEP]


def wanted(fm, step, failed="", block=None):
    """-> why `auto` switches the cause step on after this step, or "".

    only the flow's first own step is read, and only for two things: its red
    test failing a second time (`failed` is the gate that failed once the
    step has no go left), or a DID naming more than one cause: the step is
    paid for when the run shows it is guessing at the cause, not on every run.
    """
    if investigating(fm.raw) != AUTO or len(fm.steps) < 2 \
            or fm.steps[0].get("role") != INVESTIGATOR \
            or step != step_id(fm.steps[1]):
        return ""
    if failed == RED:
        return (step + " failed its " + RED + " gate twice, so its test is "
                "not yet against the cause")
    causes = [l for l in (block or {}).get("did", [])
              if NAMES_A_CAUSE.search(l)]
    if len(causes) > 1:
        return (step + " named " + str(len(causes)) + " causes in its DID:\n"
                + "\n".join("- " + c for c in causes))
    return ""


def plan_words(fm):
    """-> what the investigator is told on top of its role in `plan` mode."""
    if investigating(fm.raw) != "plan":
        return ""
    return (resolver.HERE / "fragments" / "investigate-plan.md").read_text(
        encoding="utf-8")


def sections(text):
    """-> {label: [its lines, the label's own first]}, in the order found.

    a label's lines are the one it is on and the `- ` lines under it. anything
    else ends it, which is how a code block under the answer is left out.
    """
    out = {}
    at = None
    for line in (text or "").split("\n"):
        line = line.rstrip()
        hit = LABEL.match(line.strip())
        if hit:
            at = hit.group(1)
            out[at] = [line.strip()]
        elif at and line.strip().startswith("- "):
            out[at].append(line.strip())
        elif line.strip():
            at = None
    return out


def listed(found, label):
    """-> the `- ` lines under a label, with a lone `none` left out."""
    lines = found.get(label, [])[1:]
    return [l for l in lines if l[2:].strip().lower().rstrip(".") != "none"]


def handed(text):
    """-> the block the steps after the investigator get, "" for none."""
    found = sections(text)
    lines = [l for label in HANDED for l in found.get(label, [])]
    if not lines:
        return ""
    return ("\n\nwhat " + STEP + " found before anything was changed. the test "
            "is written against the CAUSE, and every one of the SITES is this "
            "run's to fix:\n\n" + "\n".join(lines) + "\n")


def scope(prompt, text):
    """{SCOPE}: what a patch may touch. the test's reach, or the named sites."""
    if SCOPE not in prompt:
        return prompt
    named = listed(sections(text), "SITES")
    return prompt.replace(SCOPE, NAMED if named else REACHED)


def unrooted(step, text):
    """-> why the run waits for a person after the investigator, or ""."""
    if step != STEP:
        return ""
    said = sections(text).get("ROOTED")
    if not said:
        return ""
    value = said[0].split(":", 1)[1].strip()
    if not value.lower().startswith("no"):
        return ""
    gap = value[2:].strip(" ,.-")
    return (STEP + " could not prove the cause"
            + (": " + gap if gap else ", and did not say what is missing"))


def for_the_person(text):
    """-> the lines that go to the run's output and not to the fix, or ""."""
    found = sections(text)
    out = []
    for label in FOR_THE_PERSON:
        lines = listed(found, label)
        if lines:
            out.append(label + ", seen on the way and not done in this run:"
                       if label == "RELATED" else
                       label + ", for you to make:")
            out.extend(lines)
    return "\n".join(out)
