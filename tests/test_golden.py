"""what each shipped flow does, path by path, held against tests/golden/.

a replay runs the real `main()` over a shipped flow with the cli provider
answering from a script instead of a process, and keeps what a person or the
next run reads: the steps it took and where each one sent the work, every
gate, the journal and index lines, the handoff, the files left behind and
what it printed, plus a sha256 of each prompt sent: the script answers by
step and go, so without them an edited prompt replays the old answer and
passes. times, run ids, seconds and the temp place are taken out
first, so the same run on another day, machine or OS reads the same.

`python -m pytest tests/test_golden.py --update-golden` rewrites the files.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest
from conftest import answering

sys.path.insert(0, ".")
from agentweft.evals import recording
from agentweft.evals import steps as took
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, resume, ruling, trace

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
REPO = HERE.parent
FLOWS = REPO / "flows"
TEST_FLOWS = HERE / "flows"
MODEL = "model-in-replay"
VERSION = "2.1.296"


def say(text, writes=None):
    """an answer that also leaves files in the place, the way a model run
    there edits them."""
    return {"say": text, "writes": writes or {}}


def limited():
    """the account's usage limit refusing the call: an error result with no
    tokens in it, and the reset as the cli gives it."""
    return {"say": "", "writes": {}, "error": {
        "type": "result", "is_error": True,
        "result": "You've hit your usage limit",
        "api_error": "usage_limit_reached",
        "api_error_params": {"rate_limit_info": {"resetsAt": 1893456000}},
        "total_cost_usd": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "modelUsage": {}}}


BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    total = a + b\n    return total\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"

ONE_FINDING = "- [high] app.py:12 the loop reads one past the end of items\n"
NOTES = ("## added\n- a --dry-run switch on the export\n\n"
         "## fixed\n- the export no longer drops the last row\n")
SUMMARY = ("notes.md: the plan moved to friday (line 3)\n\n"
           "deleted: nothing, every line was backed\n")
DIGEST = ("## changed\n- notes.md: the plan moved to friday\n\n"
          "## needs me\n- rent.md: due on the 1st\n\n"
          "## can wait\n- garden.md: order seeds in march\n")
DIGEST_PLAN = ("notes.md | changed | the plan moved to friday\n"
               "rent.md | needs-me | due on the 1st\n")
AUDIT_PLAN = ("app.py | the entry point\n"
              "config.py | reads the settings\n")
AUDIT = ("app.py parses argv and calls run().\n"
         "config.py loads settings.yml and has no defaults, which is the risk.\n")

BUG = "add(1, 2) returns -1"
# a report pasted from a non-English tracker: cp1252 has no byte for most of it
BUG_REPORT = ("add(1, 2) " + chr(0x2192) + " -1\n\n" + chr(0x41f) + chr(0x440)
              + chr(0x438) + chr(0x43c) + chr(0x435) + chr(0x440) + ": "
              + chr(0x6f22) + chr(0x5b57) + "\n")
def block(did, verified, doubts="none", must="none", read="none"):
    """the HANDOFF block every role is asked to end with, filled in."""
    return ("\nHANDOFF\nDID:\n- " + did + "\nVERIFIED:\n- " + verified
            + "\nNOT VERIFIED:\n- none\nASSUMED:\n- none\nDOUBTS:\n- "
            + doubts + "\nMUST NOT MISS:\n- " + must + "\nTRIED:\n- none\n"
            "READ:\n- " + read + "\nEND HANDOFF\n")


FIXES = {
    "worker.md": [say("FAILS: assert -1 == 3\nTEST: test_calc.py\n\n" + TEST
                      + block("add(1, 2) is -1: calc.py:2 returns a - b",
                              "the test fails on the code as it stands | cmd:"
                              " python -m pytest -q test_calc.py | saw: 1 failed",
                              must="the task - add(1, 2) is 3",
                              read="calc.py:1-2 - the one function"),
                      {"test_calc.py": TEST})],
    "patcher.md": [say("TEST: test_calc.py\n\n-    return a - b\n"
                       "+    total = a + b\n+    return total\n"
                       + block("add returns a + b; it subtracted",
                               "1 passed | cmd: python -m pytest -q"
                               " test_calc.py | saw: 1 passed",
                               doubts="nothing else calls add, so no caller"
                               " was checked"),
                       {"calc.py": FIXED})]}

FEATURE = "calc gets mul(a, b), which multiplies"
ADD_ONLY = "def add(a, b):\n    return a + b\n"
WITH_MUL = ADD_ONLY + "\n\ndef mul(a, b):\n    return a * b\n"
MUL_TEST = ("def test_mul():\n    from calc import mul\n\n"
            "    assert mul(2, 3) == 6\n")
MUL_PLAN = "- mul(2, 3) is 6 | calc.py\n"
MUL_RED = say("FAILS: ImportError: cannot import name 'mul' from 'calc'\n"
              "TEST: test_mul.py\n\n" + MUL_TEST, {"test_mul.py": MUL_TEST})
MUL_BUILT = "- calc.py: mul(a, b) added\n"
MUL_SPEC = "# calc\n\nmul(a, b) returns a times b\n"
MUL_NEEDS = ("NEEDS: should mul round a float product to an int?\n"
             "CITES:\n- TASK.md:3 - mul(a, b) returns a times b\n"
             "OPTIONS:\n- keep: return the product as it is\n"
             "- round: round it to an int\n")
MUL_DECIDED = ("DECIDED: keep: return the product as it is\n"
               "why: TASK.md:3 says a times b and nothing about rounding\n")
ADD_SPEC = "# calc\n\ncalc only adds; it has no other operation\n"
ADD_CONFLICT = ('CONFLICT: TASK.md:3 "calc only adds; it has no other'
                ' operation"\nrequest: ' + FEATURE + "\n")

NOTES_MD = "the plan moved to friday\nthe rent is due on the 1st\n"
ASKS = ("NEEDS: notes.md has a plan line and a money line; summarise both?\n"
        "OPTIONS:\n- only the plan line\n- both lines\n")
DECLINES = 'REFUSED: notes.md:2 "the rent is due on the 1st" is money, not notes\n'
LAST = "<the run the leg before left>"

CASES = {
    ("build-feature", "pass"): {"place": {"calc.py": ADD_ONLY},
                                "args": ["--task", FEATURE], "answers": {
        "planner.md": [MUL_PLAN],
        "tester.md": [MUL_RED],
        "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL})],
        "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("build-feature", "redo"): {"place": {"calc.py": ADD_ONLY},
                                "args": ["--task", FEATURE], "answers": {
        "planner.md": [MUL_PLAN],
        "tester.md": [MUL_RED],
        "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL}),
                      say(MUL_BUILT + "- test_mul.py: mul(-2, 3) is -6\n",
                          {"test_mul.py": MUL_TEST + "\n\ndef test_mul_neg():\n"
                           "    from calc import mul\n\n"
                           "    assert mul(-2, 3) == -6\n"})],
        "reviewer.md": ["VERDICT: redo\n\nmul is not tried on a negative "
                        "number\n",
                        "VERDICT: ok\n\n" + MUL_BUILT
                        + "- test_mul.py: mul(-2, 3) is -6\n"]}},
    ("build-feature", "gate-fail"): {"place": {"calc.py": ADD_ONLY},
                                     "args": ["--task", FEATURE], "answers": {
        "planner.md": [MUL_PLAN],
        "tester.md": [say("TEST: test_mul.py\n\n" + MUL_TEST,
                          {"test_mul.py": MUL_TEST})] * 2}},
    ("code-review", "pass"): {"answers": {
        "worker.md": [ONE_FINDING],
        "reviewer.md": ["VERDICT: ok\n\n" + ONE_FINDING]}},
    ("code-review", "redo"): {"answers": {
        "worker.md": ["- [high] app.py the loop reads one past the end\n",
                      ONE_FINDING],
        "reviewer.md": ["VERDICT: redo\n\nthe finding on app.py has no line\n",
                        "VERDICT: ok\n\n" + ONE_FINDING]}},
    ("code-review", "model-map"): {
        "args": ["--model-for", "worker=low,reviewer=opus"],
        "env": {"MODEL_LOW": "low-in-replay"},
        "answers": {
            "worker.md": [ONE_FINDING],
            "reviewer.md": ["VERDICT: ok\n\n" + ONE_FINDING]}},
    ("fix-with-test", "pass"): {"place": {"calc.py": BUGGY},
                                "args": ["--task", BUG], "task": BUG,
                                "answers": FIXES},
    ("fix-with-test", "task-file"): {"place": {"calc.py": BUGGY,
                                               "bug.md": BUG_REPORT},
                                     "args": ["--task-file", "bug.md"],
                                     "task": BUG_REPORT, "answers": FIXES},
    ("fix-with-test", "gate-fail"): {"place": {"calc.py": BUGGY},
                                     "args": ["--task", BUG], "task": BUG,
                                     "answers": {
        "worker.md": ["could not make it fail: add(1, 2) looks right to me\n"]
        * 2}},
    ("code-review", "task-refused"): {"args": ["--task", BUG], "answers": {}},
    ("ops-check", "pass"): {"answers": {
        "planner.md": ["- app.log: the nightly export\n"],
        "worker.md": ["- [high] app.log: ERROR nightly-export failed: "
                      "disk full\n"],
        "reviewer.md": ["VERDICT: ok\n\n- [high] app.log: ERROR "
                        "nightly-export failed: disk full\n"]}},
    ("ops-check", "redo"): {"answers": {
        "planner.md": ["- app.log: the nightly export\n"],
        "worker.md": ["- [high] the export failed\n",
                      "- [high] app.log: ERROR nightly-export failed: "
                      "disk full\n"],
        "reviewer.md": ["VERDICT: redo\n\nthe finding lost its raw line\n",
                        "VERDICT: ok\n\n- [high] app.log: ERROR "
                        "nightly-export failed: disk full\n"]}},
    ("release-notes", "pass"): {"answers": {
        "worker.md": [NOTES],
        "reviewer.md": ["VERDICT: ok\n\n" + NOTES]}},
    ("release-notes", "redo"): {"answers": {
        "worker.md": ["## added\n- a3f9c01 a --dry-run switch (sam)\n", NOTES],
        "reviewer.md": ["VERDICT: redo\n\na hash and an author name are in "
                        "the notes\n", "VERDICT: ok\n\n" + NOTES]}},
    ("repo-audit", "pass"): {"answers": {
        "planner.md": [AUDIT_PLAN],
        "worker.md": {1: ["app.py parses argv and calls run().\n"],
                      2: ["config.py loads settings.yml, no defaults.\n"]},
        "merge.md": [AUDIT],
        "reviewer.md": ["VERDICT: ok\n\n" + AUDIT]}},
    ("repo-audit", "redo"): {"answers": {
        "planner.md": [AUDIT_PLAN],
        "worker.md": {1: ["app.py parses argv and calls run().\n",
                          "app.py parses argv and calls run().\n"],
                      2: ["config.py loads settings.yml, no defaults.\n",
                          "config.py loads settings.yml (port, log_dir), "
                          "no defaults.\n"]},
        "merge.md": ["app.py parses argv and calls run().\n"
                     "config.py loads settings.yml and has no defaults.\n",
                     AUDIT],
        "reviewer.md": ["VERDICT: redo\n\nconfig.py: which settings were "
                        "read is not said\n", "VERDICT: ok\n\n" + AUDIT]}},
    ("summarise-and-check", "pass"): {"answers": {
        "worker.md": [SUMMARY],
        "reviewer.md": ["VERDICT: ok\n\n" + SUMMARY]}},
    ("summarise-and-check", "redo"): {"answers": {
        "worker.md": ["notes.md: the plan moved\n", SUMMARY],
        "reviewer.md": ["VERDICT: redo\n\nnotes.md: no line is named\n",
                        "VERDICT: ok\n\n" + SUMMARY]}},
    ("weekly-digest", "pass"): {"answers": {
        "planner.md": [DIGEST_PLAN],
        "worker.md": {1: ["- notes.md: the plan moved to friday\n"],
                      2: ["- rent.md: due on the 1st\n"]},
        "merge.md": [DIGEST],
        "reviewer.md": ["VERDICT: ok\n\n" + DIGEST]}},
    ("weekly-digest", "gate-fail"): {"answers": {
        "planner.md": [DIGEST_PLAN],
        "worker.md": {1: ["- notes.md: the plan moved to friday\n"],
                      2: ["- rent.md: due on the 1st\n"]},
        "merge.md": [DIGEST],
        "reviewer.md": ["VERDICT: ok\n\nhere is your digest\n\n" + DIGEST] * 2}},
    ("weekly-digest", "redo"): {"answers": {
        "planner.md": [DIGEST_PLAN],
        "worker.md": {1: ["- notes.md: the plan moved to friday\n",
                          "- notes.md: the plan moved to friday (line 3)\n"],
                      2: ["- rent.md: due on the 1st\n",
                          "- rent.md: due on the 1st (line 1)\n"]},
        "merge.md": [DIGEST + "- garden.md: order seeds in march\n", DIGEST],
        "reviewer.md": ["VERDICT: redo\n\ngarden.md was never in the plan\n",
                        "VERDICT: ok\n\n" + DIGEST]}},
    ("risky-edit", "hot-park"): {
        "flows": TEST_FLOWS,
        "ranking": "src/hooks.ts 0.94\nsrc/util.ts 0.11\n",
        "answers": {
            "planner.md": ["the retry loop backs off too late\n"],
            "worker.md": ["edited src/hooks.ts: the retry loop backs off "
                          "before the third call\n"]}},
    ("risky-edit", "hot-plan"): {
        "flows": TEST_FLOWS,
        "ranking": "src/hooks.ts 0.94\nsrc/util.ts 0.11\n",
        "answers": {
            "planner.md": ["src/hooks.ts: the retry loop lives there\n"]}},
    ("release-notes", "outage-resume"): {
        "legs": [[], ["--resume", LAST]],
        "answers": {
            "worker.md": [NOTES],
            "reviewer.md": [limited(), "VERDICT: ok\n\n" + NOTES]}},
    ("capped", "budget-resume"): {
        "flows": TEST_FLOWS,
        "legs": [[], ["--resume", LAST],
                 ["--resume", LAST, "--max-calls", "2"]],
        "answers": {
            "worker.md": [NOTES],
            "reviewer.md": ["VERDICT: ok\n\n" + NOTES]}},
    ("fix-with-test", "chained-resume"): {
        "place": {"calc.py": BUGGY}, "args": ["--task", BUG], "task": BUG,
        "legs": [[], ["--resume", LAST], ["--resume", LAST]],
        "answers": {"worker.md": FIXES["worker.md"],
                    "patcher.md": [limited(), limited()]
                    + FIXES["patcher.md"]}},
    ("summarise-and-check", "ruling-resume"): {
        "place": {"notes.md": NOTES_MD},
        "legs": [[], ["--resume", LAST],
                 ["--resume", LAST, "--answer", "only the plan line"]],
        "answers": {
            "worker.md": [ASKS, SUMMARY],
            "reviewer.md": ["VERDICT: ok\n\n" + SUMMARY]}},
    ("summarise-and-check", "refused"): {
        "place": {"notes.md": NOTES_MD},
        "legs": [[], ["--resume", LAST]],
        "answers": {"worker.md": [DECLINES]}},
    ("build-feature", "conflict"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": ADD_SPEC},
        "args": ["--task", FEATURE],
        "legs": [[], ["--resume", LAST, "--answer",
                      "override: calc may multiply now"]],
        "answers": {
            "planner.md": [ADD_CONFLICT, MUL_PLAN],
            "tester.md": [MUL_RED],
            "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("build-feature", "lead-decides"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": MUL_SPEC},
        "args": ["--task", FEATURE], "answers": {
            "planner.md": [MUL_PLAN, MUL_DECIDED],
            "tester.md": [MUL_RED],
            "worker.md": [MUL_NEEDS, say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
}


class Script(object):
    """the cli process, answering each step from its list in turn.

    a fanned-out step's tasks run on threads in no fixed order, so each task
    has a list of its own, picked by the task number the step was asked with.
    """

    def __init__(self, answers, place):
        self.answers = answers
        self.place = place
        self.asked = {}
        self.prompts = []
        self.lock = threading.Lock()
        self.now = threading.local()

    def asking(self, step, task):
        self.now.step, self.now.task = step, task

    def run(self, argv, **kw):
        if argv[1:] == ["--version"]:
            return types.SimpleNamespace(returncode=0, stderr="",
                                         stdout=VERSION + " (Claude Code)\n")
        # a checkout with CRLF endings would send a different prompt than a
        # Linux one, which the counted usage below would never show
        assert "\r" not in (kw.get("input") or ""), "a prompt kept a CR"
        step, task = self.now.step, self.now.task
        planned = self.answers.get(step)
        if isinstance(planned, dict):
            planned = planned.get(task)
        with self.lock:
            n = self.asked.get((step, task), 0)
            self.asked[(step, task)] = n + 1
            self.prompts.append((step, task, n + 1, kw.get("input") or ""))
        if not planned or n >= len(planned):
            raise AssertionError("the script has no answer " + str(n + 1)
                                 + " for " + step
                                 + ("" if task is None else " task " + str(task)))
        answer = planned[n]
        if isinstance(answer, str):
            answer = say(answer)
        for rel, text in answer["writes"].items():
            (self.place / rel).write_bytes(text.encode("utf-8"))
        session = step[:-3] + ("" if task is None else "-" + str(task)) \
            + "-" + str(n + 1)
        if answer.get("error"):
            out = json.dumps(dict(answer["error"], session_id=session))
            return types.SimpleNamespace(returncode=1, stdout=out, stderr="")
        out = json.dumps({"type": "result", "is_error": False,
                          "result": answer["say"], "session_id": session,
                          "total_cost_usd": 0.01,
                          "usage": {"input_tokens": 100, "output_tokens": 20},
                          "modelUsage": {MODEL: {}}})
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    def unused(self):
        left = []
        for step, planned in self.answers.items():
            lists = planned.items() if isinstance(planned, dict) \
                else [(None, planned)]
            for task, answers in lists:
                n = self.asked.get((step, task), 0)
                if n < len(answers):
                    left.append((step, task, len(answers) - n))
        return left


def replay(flow, case, tmp_path, monkeypatch, capsys):
    place = tmp_path / "place"
    place.mkdir()
    for rel, text in (case.get("place") or {}).items():
        (place / rel).write_bytes(text.encode("utf-8"))
    monkeypatch.chdir(place)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(case.get("flows", FLOWS))])
    for key in list(os.environ):
        if key.startswith("MODEL_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("MODEL", MODEL)
    for key, value in case.get("env", {}).items():
        monkeypatch.setenv(key, value)
    for key in prompts.ENV_KEYS:
        monkeypatch.setenv(key, "inbox")
    # the risk map is a server the place would have to be running; none is,
    # so a case that needs a ranking carries the one the server would answer
    ranked = (case["ranking"], "") if case.get("ranking") \
        else ("", "no server in a replay")
    monkeypatch.setattr(engine.context, "risk_map",
                        lambda config, where=None: ranked)

    script = Script(case["answers"], place)
    real_step = engine.Run.step

    def step(self, name, previous=engine.EMPTY, extra="", task=None, last=""):
        script.asking(name, task)
        return real_step(self, name, previous=previous, extra=extra, task=task,
                         last=last)

    monkeypatch.setattr(engine.Run, "step", step)
    monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
        run=script.run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(cli_provider, "call", answering(script.run))

    # an answer says who gave it, and that is whoever runs the suite
    monkeypatch.setattr(ruling, "who", lambda: "the operator")

    legs = case.get("legs")
    codes, raises, prints = [], [], []
    for n, leg in enumerate(legs or [[]]):
        if n:
            # each leg a minute on, so a resume never shares the second, and
            # with it the -2 on the id, with the run it picks up
            clock = later(datetime.timedelta(minutes=n))
            monkeypatch.setattr(engine, "datetime", clock)
            monkeypatch.setattr(trace, "datetime", clock)
        if LAST in leg:
            leg = [resume.runs_for(flow)[-1] if a == LAST else a for a in leg]
        monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force"]
                            + case.get("args", []) + leg)
        capsys.readouterr()
        raised = None
        code = None
        try:
            code = engine.main()
        except Exception as e:
            raised = type(e).__name__ + ": " + str(e)
        codes.append(code)
        raises.append(raised)
        prints.append(said(capsys.readouterr().out))
    assert script.unused() == [], "answers the run never asked for"
    if legs:
        code, raised, printed = codes, raises, prints
    else:
        code, raised, printed = codes[0], raises[0], prints[0]
    if case.get("task"):
        # fix-with-test names worker.md for its task; the steps after it work
        # from what the worker handed on
        for step, _, _, prompt in script.prompts:
            assert (case["task"] in prompt) == (step == "worker.md"), step
    got = normalise(record(tmp_path / "runs", code, raised, printed), tmp_path)
    # sorted again once the stamps are out: "<flow>-<day>-1.md" against the
    # run folder "<flow>-<day>-<time>/" orders by the hour the run started in
    got["files"] = sorted(got["files"])
    got["prompts"] = sorted(
        recording.named(step, task, n) + " "
        + recording.digest(scrub(prompt, tmp_path))
        for step, task, n, prompt in script.prompts)
    return got


def text_lines(path):
    if not path.exists():
        return []
    return [l for l in path.read_bytes().decode("utf-8").replace("\r\n", "\n")
            .split("\n") if l.strip()]


def record(runs, code, raised, printed):
    steps = []
    handoff = []
    # a run refused before it started leaves no runs folder at all
    runs.mkdir(parents=True, exist_ok=True)
    for folder in sorted(p for p in runs.iterdir() if p.is_dir()):
        steps = steps + took.read(folder)
        handoff = handoff + text_lines(folder / "handoff.md")
    return {
        "exit": code,
        "raised": raised,
        "path": [str(l["seq"]) + " " + took.said(l) for l in steps],
        "journal": text_lines(runs / "journal.md"),
        "index": text_lines(runs / "index.md"),
        "handoff": handoff,
        "files": sorted(p.relative_to(runs).as_posix()
                        for p in runs.rglob("*") if p.is_file()),
        "steps": steps,
        "printed": printed,
    }


def said(printed):
    return [l.rstrip() for l in printed.replace("\r\n", "\n").split("\n")
            if l.strip()]


STAMPS = (
    # the last-run file is named by a hash of the place, which is a temp dir
    (re.compile(r"^(last-run-\S+)-[0-9a-f]{16}(?=\.json)"), r"\1-<key>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}"), "<run>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?"), "<time>"),
    (re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"), "<time>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<day>"),
    # the journal's run time and the handoff's per-step seconds
    (re.compile(r"(?<=  )\d+s(?=  |$)"), "<secs>s"),
    (re.compile(r"(?m)^(  \S+ +)\d+(\.\d+)?s$"), r"\1<secs>s"),
    # the handoff's "ran ... in 4.2s" and "- steps: worker.md 1.3s -> ..."
    (re.compile(r"(?<= in )\d+(\.\d+)?s(?= on:|\.)"), "<secs>s"),
    (re.compile(r"(?<=\.md )\d+(\.\d+)?s(?= ->| \(|$)"), "<secs>s"),
)
CLOCKED = ("time", "seconds")


def spellings(path):
    out = set()
    for p in (path, path.resolve()):
        out.add(str(p))
        out.add(p.as_posix())
    return sorted(out, key=len, reverse=True)


def scrub(text, tmp_path):
    text = text.replace("\r\n", "\n")
    # the interpreter first: it may sit inside the checkout, in a venv
    for where, name in ((Path(sys.executable), "<python>"),
                        (tmp_path, "<tmp>"), (REPO, "<repo>")):
        for spelt in spellings(where):
            text = text.replace(spelt, name)
    text = text.replace("\\", "/")
    for pattern, put in STAMPS:
        text = pattern.sub(put, text)
    return text


def normalise(value, tmp_path):
    """-> value with nothing in it that differs between two runs of the same
    script: no clock, no run id, no seconds, no temp or checkout path."""
    if isinstance(value, dict):
        return {k: ("<" + k + ">" if k in CLOCKED and v is not None
                    else normalise(v, tmp_path)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v, tmp_path) for v in value]
    if isinstance(value, str):
        return scrub(value, tmp_path)
    return value


def dump(value):
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def golden_file(flow, path):
    return GOLDEN / flow / (path + ".json")


def compare(flow, path, got, update):
    target = golden_file(flow, path)
    if update:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(dump(got).encode("utf-8"))
        return
    assert target.exists(), (str(target.relative_to(REPO)) + " is missing. "
                             "python -m pytest tests/test_golden.py "
                             "--update-golden writes it")
    want = json.loads(target.read_bytes().decode("utf-8"))
    assert dump(got).split("\n") == dump(want).split("\n")


@pytest.mark.parametrize("flow,path", sorted(CASES),
                         ids=[f + "/" + p for f, p in sorted(CASES)])
def test_a_shipped_flow_does_what_its_golden_says(flow, path, tmp_path,
                                                  monkeypatch, capsys,
                                                  update_golden):
    got = replay(flow, CASES[(flow, path)], tmp_path, monkeypatch, capsys)
    compare(flow, path, got, update_golden)


def shipped():
    return sorted(p.name for p in FLOWS.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def test_every_shipped_flow_has_its_pass_path_pinned():
    assert sorted(f for f, p in CASES if p == "pass") == shipped()


def test_every_golden_file_has_a_replay_behind_it():
    on_disk = sorted((p.parent.name, p.stem) for p in GOLDEN.glob("*/*.json"))
    assert on_disk == sorted(CASES)


@pytest.mark.parametrize("edit", [False, True], ids=["as-shipped", "edited"])
def test_an_edited_prompt_does_not_replay_its_golden_silently(
        edit, tmp_path, monkeypatch, capsys):
    flows = tmp_path / "flows"
    shutil.copytree(FLOWS / "code-review", flows / "code-review")
    if edit:
        worker = flows / "code-review" / "worker.md"
        worker.write_bytes(worker.read_bytes() + b"\nname the file first.\n")
    got = replay("code-review", dict(CASES[("code-review", "pass")],
                                     flows=flows),
                 tmp_path, monkeypatch, capsys)
    if not edit:
        compare("code-review", "pass", got, False)
        return
    with pytest.raises(AssertionError):
        compare("code-review", "pass", got, False)
    want = json.loads(golden_file("code-review", "pass").read_bytes())
    assert [p for p in got["prompts"] if p not in want["prompts"]] == [
        p for p in got["prompts"] if p.startswith("worker.md ")]


SHIFT = datetime.timedelta(days=400, hours=13, minutes=17)


class Later(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.datetime.now(tz) + SHIFT


class LaterDay(datetime.date):
    @classmethod
    def today(cls):
        return (datetime.datetime.now() + SHIFT).date()


def later(shift):
    """-> a datetime module whose clock reads `shift` ahead."""
    class Now(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime.now(tz) + shift

    class Today(datetime.date):
        @classmethod
        def today(cls):
            return (datetime.datetime.now() + shift).date()

    return types.SimpleNamespace(datetime=Now, date=Today,
                                 timedelta=datetime.timedelta)


def test_a_run_on_another_day_reads_the_same_once_normalised(
        tmp_path, monkeypatch, capsys):
    clock = types.SimpleNamespace(datetime=Later, date=LaterDay,
                                  timedelta=datetime.timedelta)
    monkeypatch.setattr(engine, "datetime", clock)
    monkeypatch.setattr(trace, "datetime", clock)
    got = replay("release-notes", CASES[("release-notes", "redo")], tmp_path,
                 monkeypatch, capsys)
    assert any(str((datetime.datetime.now() + SHIFT).year) in l
               for l in text_lines(tmp_path / "runs" / "journal.md"))
    compare("release-notes", "redo", got, False)


def test_the_normaliser_takes_out_what_differs_between_two_runs(tmp_path):
    one = {"time": "2026-01-02T03:04:05", "seconds": 1.5,
           "why": str(tmp_path / "place" / "a.py") + " at 2026-01-02 03:04",
           "line": "2026-01-02 03:04  flow  ok  7s  flow-2026-01-02-1.md",
           "run": "flow-2026-01-02-030405"}
    two = {"time": "2027-11-30T23:59:59", "seconds": 0.0,
           "why": (tmp_path / "place" / "a.py").as_posix()
           + " at 2027-11-30 23:59",
           "line": "2027-11-30 23:59  flow  ok  0s  flow-2027-11-30-1.md",
           "run": "flow-2027-11-30-235959"}
    assert normalise(one, tmp_path) == normalise(two, tmp_path)
    assert normalise(one, tmp_path)["why"] == "<tmp>/place/a.py at <time>"
