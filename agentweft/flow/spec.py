"""a flow spec: what it takes, what it gives back, and what is always true.

the steps have lived in flow.yaml since september. this adds the part that says
what the thing is FOR, so a run can be judged against something other than my
memory of what it used to look like.
"""
import difflib

from agentweft.guardrails import police


class Promises(object):
    __slots__ = ("inputs", "outputs", "invariants")

    def __init__(self, inputs="", outputs="", invariants=None):
        self.inputs = inputs
        self.outputs = outputs
        self.invariants = list(invariants or [])

    def as_prompt(self):
        if not self.invariants:
            return ""
        lines = ["", "this flow promises, every time:"]
        for i in self.invariants:
            lines.append("- " + i)
        return "\n".join(lines) + "\n"


class FlowSpec(object):
    __slots__ = ("name", "steps", "promises", "raw")

    def __init__(self, raw):
        self.raw = raw
        self.name = raw.get("name", "")
        self.steps = raw.get("steps", [])
        p = raw.get("promises") or {}
        self.promises = Promises(p.get("inputs", ""), p.get("outputs", ""),
                                 p.get("invariants"))

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def __getitem__(self, key):
        return self.raw[key]


def step_id(step):
    """what a step is called outside flow.yaml: the file its words live in.

    a role is what a step IS and the prompt file is only where its words
    happen to live, so one role can be two steps with a file each. the file
    name is what tells those two apart, which is why it is the name the
    runner, the router and the run directory all use.
    """
    return step.get("prompt", step["role"] + ".md")


def step_name(step):
    """what a step is called by another step: its file, without the `.md`.

    `reports:` is a list a person writes next to a role, and a role has never
    carried an extension there. so the step's name in that list does not carry
    one either, and a flow whose file is named after its role reads the same
    word both ways.
    """
    name = step_id(step)
    return name[:-3] if name.endswith(".md") else name


def steps_named(steps, name):
    """-> the steps `name` stands for, in flow order.

    a ROLE stands for every step that declared it, which is what makes a pair
    of personas addressable as the pair they are: the reviewer that was told
    to cut and the reviewer that was told to expand are both the reviewer, and
    a judge that was handed one of them is judging nothing. a STEP's own name
    stands for that one step, for a flow that wants a single stance judged.
    """
    return [s for s in steps if s["role"] == name or step_name(s) == name]


REQUIRED = ("name", "steps")
KNOWN = ("name", "steps", "promises", "schedule", "timeout", "retries", "workers",
         "journal", "max_calls", "max_tokens", "provider", "context", "workdir",
         "tiers", "investigate", "tests_e2e", "tests_integration", "verify",
         "send_backs", "lead", "on_stop", "spec_files", "baseline",
         "efforts", "commits", "worktree", "sacrifice", "retro", "brief",
         "reviewers", "police", "network")
# the runner's own last step (`runner/retro.py`): its role, skill and file
RETRO = "retro"
NO_LEAD = "none"
# whether the run commits as it goes (`runner/commits.py`)
COMMITS = ("none", "wip", "squash")
# when the run reads the state of the suite it started from
# (`guardrails/baseline.py`)
BASELINE = ("auto", "on", "off")
# what a stop does with the tests the run added or changed: leave them, or
# put them back to their bytes at the start (`runner/leftred.py`)
ON_STOP = ("keep", "revert-tests")
# what a step may do to the spec files (`guardrails/specfiles.py`)
SPEC_FILES = ("read-only", "additions")
STEP_KNOWN = ("role", "prompt", "fanout", "on_redo", "must_produce", "workers",
              "gates", "provider", "preflight", "pause", "model", "tools",
              "reports", "writes_tests", "writes", "effort", "verbosity",
              "continue", "brief", "lens")
WRITES = ("tests", "product", "none")
PROMISES_KNOWN = ("inputs", "outputs", "invariants")
CONTEXT_KNOWN = ("command", "arguments", "tool", "timeout")
PREFLIGHT_KNOWN = ("mode", "threshold")

# `model` on a step is a tier, not an id. the workflow file's header says the
# model names came out of the imported prompts on the way over, because a tier
# means something to any provider and a version string means something to one
# of them for about a quarter. a flow file naming one would put them back.
TIERS = ("high", "mid", "low")

# `effort` on a step is how hard its model thinks, lowest first: the words
# `claude --effort` and the api's `output_config.effort` both take.
LEVELS = ("low", "medium", "high", "xhigh", "max")

# `verbosity` on a step is how much it says back. `terse` adds
# `fragments/terse.md` to its prompt and caps its answer; `normal` is the
# same as saying nothing.
VERBOSITY = ("normal", "terse")

# `tools` on a step is what it is allowed to touch, and these are the six words
# the imported agent files have been granting each other since they arrived.
# the list is closed on purpose: a grant nothing has a name for is not a
# narrower grant, it is a word this repo cannot check anything against, and it
# would sit in a file looking like a boundary. `guardrails/boundary.py` is what
# reads a grant; this is only the vocabulary it and the flow files share.
GRANTS = ("read", "grep", "write", "edit", "shell", "browser")

PREFLIGHT_MODES = ("flag", "refuse", "park")

# `continue` on a step: `fresh` asks it with the whole prompt every time,
# `resume` carries its own earlier session in the run on and sends only what
# is new (`runner/engine.py`, `Run.carry_for`).
CONTINUE = ("fresh", "resume")
RESUME = "resume"


def brief_on(step, raw):
    """-> whether the step is sent the brief (`runner/brief.py`): its own
    `brief:`, else the flow's, else yes. off, it is not handed what the
    steps before it found and quoted, and starts from the handoff of the step
    before it."""
    for said in (step.get("brief"), raw.get("brief")):
        if said is not None:
            return bool(said)
    return True

# `investigate:` puts one step in front of the flow's own that finds the cause
# of the task and everything it reaches before anything is written. `cause` is
# the cause and its sites, `plan` adds the tests to write and what the person
# has to decide. `auto` is `cause` held back until the first step shows it
# needs one (`runner/investigate.py`). the step's name is not `planner`, which
# already means a step whose lines are fanned out and that is handed the risk
# map.
INVESTIGATE = ("off", "cause", "plan", "auto")
INVESTIGATOR = "investigator"
# one site per line, `file:function`: a few anchors and not the code, which the
# step after reads for itself
SITES = r"^SITES:[ \t]*\n(?:[ \t]*-[ \t]+\S+:\S+.*\n?)+"
ROOTED = r"^ROOTED:[ \t]*(yes|no)\b"


def investigating(raw):
    """-> the mode a flow asked for, "off" when it asked for none.

    a bare `off` in yaml is read as false, so false is off as well.
    """
    value = raw.get("investigate")
    if value is None or value is False:
        return "off"
    return value


def investigator():
    return {"role": INVESTIGATOR, "prompt": INVESTIGATOR + ".md",
            "must_produce": "CAUSE:", "tools": ["read", "grep", "shell"],
            "gates": [{"gate": "regex", "pattern": SITES},
                      {"gate": "regex", "pattern": ROOTED}]}


def with_investigator(raw):
    """-> raw, with the investigator as its first step when it asked for one."""
    if investigating(raw) not in INVESTIGATE[1:]:
        return raw
    out = dict(raw)
    out["steps"] = [investigator()] + list(raw.get("steps") or [])
    return out


# `verify:` says whether the flow's `verify` steps run. `judge` runs them as
# written, `off` takes them out, so a flow whose checks are all programs on the
# steps before keeps its judge as a line to switch on rather than a file to
# rewrite. a flow that does not say is run as written.
VERIFY = ("judge", "off")
VERIFIER = "verify"


def verifying(raw):
    """-> "judge" or "off". a flow that does not say gets "judge" when it has
    a verify step and "off" when it has none; a bare `off` reads as false."""
    value = raw.get("verify")
    if value is False:
        return "off"
    if value is None:
        steps = raw.get("steps") or []
        return "judge" if any(isinstance(s, dict) and s.get("role") == VERIFIER
                              for s in steps) else "off"
    return value


def with_verify(raw):
    """-> raw, with its verify steps taken out when it said `verify: off`."""
    if raw.get("verify") is None:
        return raw
    out = dict(raw)
    out["verify"] = verifying(raw)
    if out["verify"] == "off":
        out["steps"] = [s for s in raw.get("steps") or []
                        if s.get("role") != VERIFIER]
    return out


# `reviewers:` is how many of the flow's reviewer steps run, the first ones in
# flow order. a second reviewer is a second lens, not a second opinion: when
# a flow runs more than one, each says in `lens:` the one line it reads for,
# and no two say the same. each verdict is its own: a redo from any of them
# sends the work back, and the work comes past all of them again.
REVIEWER = "reviewer"


def reviewer_steps(raw):
    return [s for s in raw.get("steps") or []
            if isinstance(s, dict) and s.get("role") == REVIEWER]


def with_reviewers(raw):
    """-> raw, with the reviewer steps past its `reviewers:` count taken out."""
    keep = raw.get("reviewers")
    if not counts(keep):
        return raw
    out = dict(raw)
    kept = reviewer_steps(raw)[:keep]
    out["steps"] = [s for s in raw.get("steps") or []
                    if not (isinstance(s, dict) and s.get("role") == REVIEWER)
                    or any(s is k for k in kept)]
    return out


def check_reviewers(raw):
    """-> complaints about `reviewers:` and the steps' `lens:`."""
    bad = []
    steps = raw.get("steps") or []
    mine = reviewer_steps(raw)
    said = raw.get("reviewers")
    if said is not None and not (counts(said) and 1 <= said <= len(mine)):
        bad.append("reviewers should be a whole number from 1 to "
                   + str(len(mine)) + ", the reviewer steps this flow has")
    lensed = said is not None or any(s.get("lens") is not None for s in mine)
    seen = {}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if "lens" not in step and step.get("role") != REVIEWER:
            continue
        at = "step " + str(i) + ": "
        lens = step.get("lens")
        if step.get("role") != REVIEWER:
            bad.append(at + "lens is for a reviewer step, and this one is a "
                       + str(step.get("role")))
        elif lens is None:
            if lensed and len(mine) > 1:
                bad.append(at + "a flow with more than one reviewer gives each"
                           " a lens: the one line of what it reads for that"
                           " the others do not")
        elif not isinstance(lens, str) or not lens.strip() or "\n" in \
                lens.strip():
            bad.append(at + "lens should be one line saying what this"
                       " reviewer reads for")
        elif lens.strip().lower() in seen:
            bad.append(at + "lens is the same as step "
                       + str(seen[lens.strip().lower()]) + "'s; a second"
                       " reviewer reads for what the first does not")
        else:
            seen[lens.strip().lower()] = i
    return bad


# `sacrifice:` is what a flow gives up, in order, when its budget is short
# (`guardrails/sacrifice.py`): steps or roles. what guards the tests is never
# on it, by the word a person would reach for or by the step that carries it.
NEVER = {"tests": "the red test", "red-test": "the red test",
         "red-first": "the red test",
         "start-tests": "the tests the run started with",
         "command": "the suite gate"}
# the gates whose program or numbers come from project.yml: cutting the step
# that carries one switches off a check the project declared
DECLARED = ("project", "coverage", "reject")


def guards(step):
    """-> what of NEVER the step carries, "" for none."""
    gates = [g.get("gate") for g in step.get("gates") or []
             if isinstance(g, dict)]
    if step.get("writes") == "tests" or "red-test" in gates \
            or "red-first" in gates:
        return "the red test"
    if "command" in gates:
        return "the suite gate"
    if set(gates) & set(DECLARED):
        return "a check project.yml declares"
    if "verdict" in gates:
        return "a verdict gate"
    if step.get("writes") == "product":
        return "the tests the run started with"
    return ""


def check_sacrifice(raw):
    """-> complaints about `sacrifice:`, made at load and not when the money
    runs short."""
    from agentweft.guardrails.gates import registry

    said = raw.get("sacrifice")
    if said is None:
        return []
    if not isinstance(said, list):
        return ["sacrifice should be a list, one step or role per line"]
    steps = [s for s in with_investigator(raw).get("steps") or []
             if isinstance(s, dict) and "role" in s]
    names = []
    for s in steps:
        for name in (s["role"], step_name(s)):
            if name not in names:
                names.append(name)
    bad = []
    seen = []
    for name in said:
        at = "sacrifice: "
        if not isinstance(name, str):
            bad.append(at + str(name) + " is not a step or a role, one name"
                       " per line")
            continue
        if name in seen:
            bad.append(at + name + " is listed twice; name it once")
            continue
        seen.append(name)
        if name in NEVER:
            bad.append(at + name + " is never cut: it is " + NEVER[name])
        elif name in registry:
            bad.append(at + name + " is a gate, and a gate spends no calls;"
                       " the list cuts steps")
        elif name not in names:
            bad.append(at + "no step or role called " + name
                       + meant(name, names) + ". there is: "
                       + ", ".join(names))
        else:
            kept = [guards(s) for s in steps_named(steps, name) if guards(s)]
            if raw.get("verify") == "judge" and any(
                    s.get("role") == VERIFIER for s in steps_named(steps, name)):
                kept.append("the verify step `verify: judge` says the run"
                            " judges with")
            if kept:
                bad.append(at + name + " is never cut: it carries "
                           + kept[0])
    return bad


TYPES = {"timeout": int, "retries": int, "workers": int, "max_calls": int,
         "max_tokens": int, "journal": bool, "name": str, "workdir": str,
         "tests_e2e": bool, "retro": bool, "brief": bool}


def counts(value):
    """-> whether value is a count. yaml reads `yes` as true, and true is an
    int to python, so a bool is turned away by name."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def meant(word, known):
    """-> ", did you mean <the closest known word>?", or "" when none is close."""
    near = difflib.get_close_matches(str(word), list(known), n=1)
    return ", did you mean " + near[0] + "?" if near else ""


def unknown(key, known):
    return "unknown key " + str(key) + meant(key, known)


def block(where, value, known):
    """-> complaints about a nested mapping such as `context:`."""
    if not isinstance(value, dict):
        return [where + " should be a mapping"]
    return [where + ": " + unknown(k, known) for k in value if k not in known]


def check_gates(at, gates):
    """-> complaints about a step's `gates:`, made before the step is paid for.

    `gates.build` refuses the same names, but only once the step has run.
    """
    # here and not at the top: the coverage and reject gates read project.yml
    # through orchestrate, which loads this module
    from agentweft.guardrails.gates import registry

    if not isinstance(gates, list):
        return [at + "gates should be a list"]
    bad = []
    for j, g in enumerate(gates):
        if not isinstance(g, dict):
            bad.append(at + "gate " + str(j) + " should be a mapping")
            continue
        name = g.get("gate")
        if name is None:
            bad.append(at + "gate " + str(j) + " has no gate name")
            continue
        if name not in registry:
            bad.append(at + "no such gate " + str(name) + meant(name, registry)
                       + ". there is: " + ", ".join(sorted(registry)))
            continue
        takes = registry[name].options
        for k in g:
            if k != "gate" and k not in takes:
                bad.append(at + "gate " + str(name) + " has no option " + str(k)
                           + meant(k, takes)
                           + ". it takes: " + (", ".join(takes) or "nothing"))
    return bad


def check_project_gates(steps, place=None, held=None):
    """-> complaints about the `project` gates' names, against the
    project.yml of the place the run works in. made once that place is
    known, which is after the flow has loaded."""
    bad = []
    for i, step in enumerate(steps):
        for g in step.get("gates") or []:
            if isinstance(g, dict) and g.get("gate") == "project":
                bad.extend("step " + str(i) + ": " + c for c in
                           check_project_gate(g.get("name"), place, held))
    return bad


def check_project_gate(said, place=None, held=None):
    """-> complaints about a `project` gate's name, against project.yml now.

    the gate reads the file again when it runs; this is so a name the file
    does not have stops the run before any step is paid for.
    """
    import yaml

    from agentweft.orchestrate import project

    held = held or project.hold(place)
    if held.text is None:
        return ["gate project " + str(said or "") + " needs a project.yml at "
                + str(held.path) + ", where its command comes from"]
    try:
        have = held.read().gates()
    except ValueError as e:
        return [str(e)]
    except yaml.YAMLError as e:
        return ["project.yml: " + str(e)]
    if not said:
        return ["gate project needs a name, one of: "
                + (", ".join(have) or "none")]
    if said not in have:
        return ["project.yml has no gate " + str(said) + meant(said, have)
                + ". there is: " + (", ".join(have) or "none")]
    return []


def ordered(raw):
    """whether any step of the flow says what it writes."""
    return any(isinstance(s, dict) and s.get("writes") is not None
               for s in raw.get("steps") or [])


def proves_red(step):
    """whether the step has a red-test gate that wants red and runs a
    command to see it."""
    for g in step.get("gates") or []:
        if not isinstance(g, dict) or g.get("gate") != "red-test":
            continue
        red = g.get("red", True)
        if isinstance(red, str):
            red = red.strip().lower() in ("true", "yes", "on", "1")
        if red in (True, 1) and g.get("command"):
            return True
    return False


def check(raw):
    """-> list of complaints. a typo in flow.yaml used to just do nothing."""
    bad = []
    for key in REQUIRED:
        if key not in raw:
            bad.append("missing " + key)
    for key in raw:
        if key not in KNOWN:
            bad.append(unknown(key, KNOWN))
            continue
        want = TYPES.get(key)
        if want and not isinstance(raw[key], want):
            bad.append(key + " should be " + want.__name__)
    said = raw.get("tests_integration")
    if said is not None and not isinstance(said, bool) and said != "auto":
        bad.append("tests_integration should be true, false or auto")
    if "send_backs" in raw and not counts(raw["send_backs"]):
        bad.append("send_backs should be a whole number, 0 or more")
    bad.extend(check_lead(raw))
    if "on_stop" in raw and raw["on_stop"] not in ON_STOP:
        bad.append("on_stop should be one of " + ", ".join(ON_STOP))
    if "spec_files" in raw and raw["spec_files"] not in SPEC_FILES:
        bad.append("spec_files should be one of " + ", ".join(SPEC_FILES))
    if "baseline" in raw and raw["baseline"] not in BASELINE + (True, False):
        bad.append("baseline should be one of " + ", ".join(BASELINE))
    if "commits" in raw and raw["commits"] not in COMMITS:
        bad.append("commits should be one of " + ", ".join(COMMITS))
    said = raw.get("worktree")
    if said is not None and not isinstance(said, bool) and \
            not (isinstance(said, str) and said.strip()):
        bad.append("worktree should be true, false or the commit to start "
                   "from")
    if raw.get("promises") is not None:
        more = block("promises", raw["promises"], PROMISES_KNOWN)
        bad.extend(more)
        inv = raw["promises"].get("invariants") if not more else None
        if inv is not None and not isinstance(inv, list):
            bad.append("promises: invariants should be a list")
    if raw.get("context") is not None:
        bad.extend(block("context", raw["context"], CONTEXT_KNOWN))
    earlier = []
    for i, step in enumerate(raw.get("steps") or []):
        if not isinstance(step, dict) or "role" not in step:
            bad.append("step " + str(i) + " has no role")
            continue
        at = "step " + str(i) + ": "
        for key in step:
            if key not in STEP_KNOWN:
                bad.append(at + unknown(key, STEP_KNOWN))
        if step["role"] == RETRO or step_id(step) == RETRO + ".md":
            bad.append(at + "retro is the runner's look-back step (`retro:"
                       " true`), so no step is called retro or reads retro.md")
        if not isinstance(step.get("writes_tests", False), bool):
            bad.append(at + "writes_tests should be true or false")
        if not isinstance(step.get("brief", True), bool):
            bad.append(at + "brief should be true or false")
        if step.get("writes") is not None and step["writes"] not in WRITES:
            bad.append(at + "writes should be one of " + ", ".join(WRITES))
        if step.get("writes") is None and ordered(raw):
            bad.append(at + "another step says what it writes, so this one"
                       " has to as well: writes: " + " | ".join(WRITES))
        if step.get("writes") == "tests" and not proves_red(step):
            bad.append(at + "writes: tests needs a red-test gate with red:"
                       " true and a command, the only gate that shows a test"
                       " it wrote failing before product code is written")
        if step.get("gates") is not None:
            bad.extend(check_gates(at, step["gates"]))
        if step.get("preflight") is not None:
            pre = step["preflight"]
            bad.extend(at + c for c in block("preflight", pre, PREFLIGHT_KNOWN))
        if step.get("model") and step["model"] not in TIERS:
            bad.append("step " + str(i) + ": model should be one of "
                       + ", ".join(TIERS))
        if step.get("effort") is not None and step["effort"] not in LEVELS:
            bad.append("step " + str(i) + ": effort should be one of "
                       + ", ".join(LEVELS))
        if step.get("verbosity") is not None \
                and step["verbosity"] not in VERBOSITY:
            bad.append("step " + str(i) + ": verbosity should be one of "
                       + ", ".join(VERBOSITY))
        # `is not None` rather than truthiness: `tools: []` is a step saying it
        # may touch nothing, which is a boundary and not a missing one.
        if step.get("tools") is not None:
            if not isinstance(step["tools"], list):
                bad.append("step " + str(i) + ": tools should be a list")
            else:
                for tool in step["tools"]:
                    if tool not in GRANTS:
                        bad.append("step " + str(i) + ": no such tool "
                                   + str(tool) + ". there is: "
                                   + ", ".join(GRANTS))
        if step.get("continue") is not None:
            bad.extend(at + c for c in check_continue(step))
        pre = step.get("preflight")
        if isinstance(pre, dict) and \
                pre.get("mode", "flag") not in PREFLIGHT_MODES:
            bad.append("step " + str(i) + ": preflight mode should be one of "
                       + ", ".join(PREFLIGHT_MODES))
        if step.get("reports") is not None:
            if not isinstance(step["reports"], list):
                bad.append("step " + str(i) + ": reports should be a list")
            else:
                for name in step["reports"]:
                    if name not in earlier:
                        bad.append("step " + str(i) + ": reports " + str(name)
                                   + ", which is not a role or a step before "
                                   "it. there is: "
                                   + (", ".join(earlier) or "nothing"))
        for name in (step["role"], step_name(step)):
            if name not in earlier:
                earlier.append(name)
    if investigating(raw) not in INVESTIGATE:
        bad.append("investigate should be one of " + ", ".join(INVESTIGATE))
    said = raw.get("verify")
    if said is not None and verifying(raw) not in VERIFY:
        bad.append("verify should be one of " + ", ".join(VERIFY))
    elif said == "judge" and not any(
            isinstance(s, dict) and s.get("role") == VERIFIER
            for s in raw.get("steps") or []):
        bad.append("verify: judge, but no step has the role verify")
    bad.extend(check_tiers(with_investigator(raw)))
    bad.extend(check_tiers(with_investigator(raw), "efforts", LEVELS, "level"))
    bad.extend(check_sacrifice(raw))
    bad.extend(check_reviewers(raw))
    bad.extend(police.check_keys(raw))
    return bad


def check_continue(step):
    if step["continue"] not in CONTINUE:
        return ["continue should be one of " + ", ".join(CONTINUE)]
    if step["continue"] == RESUME and step.get("fanout"):
        return ["continue: resume on a fanned-out step, whose tasks run side"
                " by side with no one session to carry on"]
    return []


def lead_of(raw):
    """-> the id of the step a flow's `lead:` names, or None when it names
    none. a role stands for its first step."""
    said = raw.get("lead") if hasattr(raw, "get") else None
    if not isinstance(said, str) or said == NO_LEAD:
        return None
    steps = [s for s in raw.get("steps") or [] if isinstance(s, dict)
             and "role" in s]
    named = steps_named(steps, said) or [s for s in steps
                                         if step_id(s) == said]
    return step_id(named[0]) if named else None


def check_lead(raw):
    """`lead:` is a step or a role of the flow, or `none`, and never the
    fanned step: one decision cannot come from N copies."""
    if "lead" not in raw:
        return []
    said = raw["lead"]
    if not isinstance(said, str) or not said.strip():
        return ["lead should be a step of the flow, or " + NO_LEAD]
    if said == NO_LEAD:
        return []
    steps = [s for s in raw.get("steps") or [] if isinstance(s, dict)
             and "role" in s]
    found = lead_of(raw)
    if found is None:
        names = [step_name(s) for s in steps]
        return ["lead names no step of the flow: " + said + meant(said, names)
                + ". there is: " + ", ".join(names + [NO_LEAD])]
    if any(step_id(s) == found and s.get("fanout") for s in steps):
        return ["lead: " + said + " is fanned out, and a question needs one"
                " step to decide it"]
    return []


def check_tiers(raw, key="tiers", allowed=TIERS, word="tier"):
    """`tiers:` is a tier per role, held to the same rule as a step's own,
    and `efforts:` a level per role the same way."""
    chosen = raw.get(key)
    if chosen is None:
        return []
    if not isinstance(chosen, dict):
        return [key + " should be a mapping of role to " + word]
    known = []
    for step in raw.get("steps") or []:
        if isinstance(step, dict) and step.get("role") not in known:
            known.append(step.get("role"))
    bad = []
    for role, tier in chosen.items():
        if role not in known:
            bad.append(key + ": no role called " + str(role) + ". there is: "
                       + ", ".join(str(r) for r in known))
        elif tier not in allowed:
            bad.append(key + ": " + str(role) + " should be one of "
                       + ", ".join(allowed))
    return bad


def load(raw):
    bad = check(raw)
    if bad:
        raise ValueError("flow.yaml: " + "; ".join(bad))
    return FlowSpec(with_verify(with_investigator(with_reviewers(raw))))
