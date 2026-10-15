"""a gate a person turns off for one run, by name and with a reason.

`--skip <gate>[,<gate>] "<reason>"` names the gates and says why. each named
gate still gets its line in the record, a pass that says it was not run and
why, and the skip goes into decisions.md and the handoff. `tests` is one
name for the red-test and red-first gates and the test order checks
(`guardrails/redorder.py`) together, and `--skip-tests "<reason>"` is short
for `--skip tests "<reason>"`.

a skip with no reason is refused, and so is a name that is no gate, one the
flow has no step with, or one named twice. the skips are kept as
runs/<id>/skips.json, so a run picked up later skips the same gates.
"""
import json
from pathlib import Path

from .gates.base import registry

FILE = "skips.json"
TESTS = "tests"
FLAG = "--skip"
SHORT = "--skip-tests"


def _value(argv, i):
    said = argv[i].strip() if len(argv) > i else ""
    return "" if said.startswith("-") else said


def given(argv):
    """-> ({gate: reason} the command line asks for, "") or ({}, why not)."""
    out = {}
    for i, arg in enumerate(argv):
        if arg == SHORT:
            names, reason = TESTS, _value(argv, i + 1)
            if not reason:
                return {}, (SHORT + " needs a reason: " + SHORT
                            + " \"<why this run has no tests>\"")
        elif arg == FLAG:
            names, reason = _value(argv, i + 1), _value(argv, i + 2)
            if not names:
                return {}, (FLAG + " needs the gates it skips: " + FLAG
                            + " <gate>[,<gate>] \"<reason>\"")
            if not reason:
                return {}, (FLAG + " " + names + " needs a reason: " + FLAG
                            + " " + names + " \"<why it does not apply>\"")
        else:
            continue
        for name in [n.strip() for n in names.split(",") if n.strip()]:
            if name != TESTS and name not in registry:
                return {}, (name + " is not a gate. " + FLAG + " takes: "
                            + ", ".join(sorted(list(registry) + [TESTS])))
            if name in out:
                return {}, name + " is skipped twice; name it once"
            out[name] = reason
    return out, ""


def unused(skipped, fm):
    """-> why a named gate cannot be skipped in this flow, "" when each can."""
    have = set(g.get("gate") for s in fm.steps for g in (s.get("gates") or []))
    missing = sorted(n for n in skipped if n != TESTS and n not in have)
    if not missing:
        return ""
    return ("no step of " + str(fm.name) + " has a " + ", ".join(missing)
            + " gate to skip")


def grouped(skipped):
    """-> [(gates, reason)], one per reason, the `tests` skip left out."""
    out = {}
    for name, reason in sorted(skipped.items()):
        if name != TESTS:
            out.setdefault(reason, []).append(name)
    return sorted((names, reason) for reason, names in out.items())


def said(skipped):
    """-> the handoff's lines on the skipped gates, [] for none."""
    return [", ".join(names) + " skipped: " + reason
            for names, reason in grouped(skipped)]


def save(folder, skipped):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / FILE).write_text(json.dumps(skipped, indent=1,
                                                sort_keys=True),
                                     encoding="utf-8")


def load(folder):
    """-> the {gate: reason} a run saved in `folder`, {} for none."""
    try:
        data = json.loads((Path(folder) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return dict((str(k), str(v)) for k, v in data.items() if v)
