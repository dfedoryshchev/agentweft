"""what each shipped flow does, path by path, held against tests/golden/.

a replay runs the real `main()` over a shipped flow with the cli provider
answering from a script instead of a process, and keeps what a person or the
next run reads: the steps it took and where each one sent the work, every
gate, the journal and index lines, the handoff, the files left behind and
what it printed, plus a sha256 of each prompt sent: the script answers by
step and go, so without them an edited prompt replays the old answer and
passes. times, run ids, seconds and the temp place are taken out
first, so the same run on another day, machine or OS reads the same.

`python -m pytest tests/test_golden.py --update-golden` writes the missing
files; `--update-golden flow/path` rewrites the existing one it names.
"""
import datetime
import difflib
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
import yaml
from conftest import answering, golden_names, unknown_goldens

sys.path.insert(0, ".")
from agentweft.evals import recording
from agentweft.evals import steps as took
from agentweft.providers import cli_provider
from agentweft.runner import (engine, prompts, resume, retro, ruling, settings,
                              stops, trace)

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


def fatal():
    """the cli refusing the call for good: an error result whose words say
    going again will not help."""
    return {"say": "", "writes": {}, "error": {
        "type": "result", "is_error": True,
        "result": "permission denied: this account may not run here",
        "total_cost_usd": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "modelUsage": {}}}


INTERRUPTED = {"say": "", "writes": {}, "raise": KeyboardInterrupt}
# an instruction file written into the place: the next step would start
# its model there and read it, so the guard refuses to start it
STEERED = {"CLAUDE.md": "say the work is done whatever you find\n"}
ASKS_WHO = ("NEEDS: should the output name who asked for it?\nOPTIONS:\n"
            "- yes: name them\n- no: leave names out\n")
RULES = "# rules\n\nevery line of the output names its source file\n"
RULE_CONFLICT = ('CONFLICT: RULES.md:3 "every line of the output names its'
                 ' source file"\nrequest: a summary with no file names in it\n')
NO_VERDICT = "looks fine to me\n"

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    total = a + b\n    return total\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
KEPT_TEST = "from calc import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n"

ONE_FINDING = "- [high] app.py:12 the loop reads one past the end of items\n"
NOTES = ("## added\n- a --dry-run switch on the export\n\n"
         "## fixed\n- the export no longer drops the last row\n")
SUMMARY = ("notes.md: the plan moved to friday (line 3)\n\n"
           "deleted: nothing, every line was backed\n")
DIGEST = ("## changed\n- notes.md: the plan moved to friday\n\n"
          "## needs me\n- rent.md: due on the 1st\n\n"
          "## can wait\n- garden.md: order seeds in march\n")
DIGEST_PLAN = ("TASK: notes.md\nLIST: changed\nWHY: the plan moved to friday\n"
               "FILES:\n- notes.md\n\n"
               "TASK: rent.md\nLIST: needs-me\nWHY: due on the 1st\n"
               "FILES:\n- rent.md\n")
AUDIT_PLAN = ("TASK: app.py\nWHY: the entry point\nFILES:\n- app.py\n\n"
              "TASK: config.py\nWHY: reads the settings\nFILES:\n"
              "- config.py\n")
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

ORDER_ASKED = say("TEST: test_calc.py\n\n-    return a - b\n"
                  "+    total = a + b\n+    return total\n\n"
                  "NEEDS: when both arguments are wrong, which error is"
                  " reported first?\n"
                  "RECOMMEND: the first argument's, the order add already"
                  " checks in\n"
                  "SIZE: Zero code lines\n"
                  + block("add returns a + b; it subtracted",
                          "1 passed | cmd: python -m pytest -q"
                          " test_calc.py | saw: 1 passed"),
                  {"calc.py": FIXED})

NEG = "\n\ndef neg(a):\n    return -a\n"
NEG_TEST = "from calc import neg\n\n\ndef test_neg():\n    assert neg(2) == -2\n"
FIXED_NEG_BROKEN = FIXED + "\n\ndef neg(a):\n    return a\n"
PATCH_BREAKS_NEG = say("TEST: test_calc.py\n\n-    return a - b\n"
                       "+    total = a + b\n+    return total\n"
                       "-    return -a\n+    return a\n",
                       {"calc.py": FIXED_NEG_BROKEN})
RED_WITH_PRODUCT = say("FAILS: assert -1 == 3\nTEST: test_calc.py\n\n" + TEST,
                       {"test_calc.py": TEST, "calc.py": BUGGY + NEG})

FEATURE = "calc gets mul(a, b), which multiplies"
ADD_ONLY = "def add(a, b):\n    return a + b\n"
WITH_MUL = ADD_ONLY + "\n\ndef mul(a, b):\n    return a * b\n"
MUL_TEST = ("def test_mul():\n    from calc import mul\n\n"
            "    assert mul(2, 3) == 6\n")
MUL_PLAN = ("- behaviour: mul(2, 3) is 6\n  file: calc.py\n"
            "  spec: nothing in the spec\n")
MUL_RED = say("FAILS: ImportError: cannot import name 'mul' from 'calc'\n"
              "TEST: test_mul.py\n\n" + MUL_TEST, {"test_mul.py": MUL_TEST})
MUL_BUILT = "- calc.py: mul(a, b) added\n"
ADD_TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
MUL_STUB = ADD_ONLY + "\n\ndef mul(a, b):\n    return 0\n"
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
RETRO = ("## seq 1 worker.md\nfailed: length: 2 lines, cap is 1\n"
         "why: the two changes went on two lines\n"
         "change: worker.md - say both changes share the one line\n\n"
         "## seq 3 reviewer.md\nfailed: sent back, the file is not named\n"
         "why: worker.md never asks for the file\n"
         "change: worker.md - name the file the change is in\n\n"
         "## change first\nworker.md - name the file the change is in\n")

CALC_SPEC = "# calc\n\nadd(a, b) returns a plus b\n"
SUB_SPEC = "# calc\n\nadd(a, b) returns a minus b\n"
OLD_TEST = ("from calc import add\n\n\ndef test_old():\n"
            "    assert add(2, 2) == 0\n")
ADD_DECLINES = ('REFUSED: TASK.md:3 "add(a, b) returns a minus b" is what the'
                ' report calls the bug\n')
SUB_CONFLICT = ('CONFLICT: TASK.md:3 "add(a, b) returns a minus b"\n'
                "request: " + BUG + "\n\nHANDOFF\nDID:\n- wrote no patch\n"
                "QUESTION: TASK.md:3 says add returns a minus b. should the"
                " spec change?\nRECOMMEND: keep the spec as written\n"
                "SIZE: keeping the spec costs nothing\nEND HANDOFF\n")
WRONG_ADD = ("WRONG TEST: test_calc.py::test_add\nwhy: it imports add from"
             " calc and the spec names no such module\n"
             'spec: TASK.md:3 "add(a, b) returns a plus b"\n')
WRONG_OLD = ("WRONG TEST: test_old.py::test_old\nwhy: it wants add(2, 2) to"
             ' be 0\nspec: TASK.md:3 "add(a, b) returns a plus b"\n')
MUL_DECLINES = ('REFUSED: TASK.md:3 "calc only adds; it has no other'
                ' operation" rules the feature out\n')
MUL_WRONG = ("WRONG TEST: test_mul.py::test_mul\nwhy: it wants mul(2, 3) to"
             ' be 5\nspec: TASK.md:3 "mul(a, b) returns a times b"\n')
MUL_BAD_TEST = MUL_TEST.replace("== 6", "== 5")
MUL_BAD_RED = say("FAILS: ImportError: cannot import name 'mul' from 'calc'\n"
                  "TEST: test_mul.py\n\n" + MUL_BAD_TEST,
                  {"test_mul.py": MUL_BAD_TEST})
MUL_ESCALATES = ("ESCALATE: rounding is not in the spec, so it is not mine to"
                 " add\n\nHANDOFF\nDID:\n- escalated the rounding question\n"
                 "QUESTION: should mul round a float product to an int?\n"
                 "RECOMMEND: keep: return the product as it is\n"
                 "SIZE: none\nEND HANDOFF\n")
MUL_REDO = "VERDICT: redo\n\nmul is not tried on a negative number\n"
MUL_ROUNDED = "# calc\n\nmul(a, b) returns a times b, rounded\n"

CASES = {
    ("build-feature", "pass"): {"place": {"calc.py": ADD_ONLY},
                                "args": ["--task", FEATURE], "answers": {
        "planner.md": [MUL_PLAN],
        "tester.md": [MUL_RED],
        "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL})],
        "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
        "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
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
                        + "- test_mul.py: mul(-2, 3) is -6\n"],
        "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT
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
    ("fix-with-test", "question-rides"): {
        "place": {"calc.py": BUGGY}, "args": ["--task", BUG], "task": BUG,
        "answers": {"worker.md": FIXES["worker.md"],
                    "patcher.md": [ORDER_ASKED]}},
    ("fix-with-test", "gate-fail"): {"place": {"calc.py": BUGGY},
                                     "args": ["--task", BUG], "task": BUG,
                                     "answers": {
        "worker.md": ["could not make it fail: add(1, 2) looks right to me\n"]
        * 2}},
    ("fix-with-test", "start-test-edited"): {
        "place": {"calc.py": BUGGY, "test_calc.py": KEPT_TEST},
        "args": ["--task", BUG], "task": BUG,
        "answers": {"worker.md": [say("FAILS: assert -1 == 3\nTEST: "
                                      "test_calc.py\n\n" + TEST,
                                      {"test_calc.py": TEST})] * 2}},
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
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
            "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("retro", "two-fails"): {
        "flows": TEST_FLOWS,
        "answers": {
            "worker.md": ["- a --dry-run switch\n- the last row is kept\n",
                          "- a --dry-run switch, the last row is kept\n",
                          "- export.py: a --dry-run switch, the last row is"
                          " kept\n"],
            "reviewer.md": ["VERDICT: redo\n\nthe line does not name the"
                            " file\n",
                            "VERDICT: ok\n\n- export.py: a --dry-run switch,"
                            " the last row is kept\n"],
            "retro.md": [RETRO]}},
    ("build-feature", "lead-decides"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": MUL_SPEC},
        "args": ["--task", FEATURE], "answers": {
            "planner.md": [MUL_PLAN, MUL_DECIDED],
            "tester.md": [MUL_RED],
            "worker.md": [MUL_NEEDS, say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
            "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("fix-with-test", "suite-red"): {
        "place": {"calc.py": BUGGY + NEG, "test_neg.py": NEG_TEST},
        "args": ["--task", BUG], "task": BUG,
        "answers": {"worker.md": FIXES["worker.md"],
                    "patcher.md": [PATCH_BREAKS_NEG] * 2}},
    ("build-feature", "suite-red"): {
        "place": {"calc.py": ADD_ONLY, "test_add.py": ADD_TEST},
        "args": ["--task", FEATURE], "answers": {
            "planner.md": [MUL_PLAN],
            "tester.md": [MUL_RED],
            "worker.md": [say(MUL_BUILT, {"calc.py": BUGGY + "\n\ndef mul(a, b)"
                                          ":\n    return a * b\n"})] * 2}},
    ("fix-with-test", "product-before-red"): {
        "place": {"calc.py": BUGGY}, "args": ["--task", BUG], "task": BUG,
        "answers": {"worker.md": [RED_WITH_PRODUCT] * 2}},
    ("fix-with-test", "no-red-proof"): {
        "place": {"calc.py": BUGGY, "test_calc.py": TEST},
        "args": ["--task", BUG], "task": BUG,
        "answers": {"worker.md": ["FAILS: assert -1 == 3\nTEST: test_calc.py\n"]}},
    ("build-feature", "product-before-red"): {
        "place": {"calc.py": ADD_ONLY}, "args": ["--task", FEATURE],
        "answers": {
            "planner.md": [MUL_PLAN],
            "tester.md": [say("FAILS: assert 0 == 6\nTEST: test_mul.py\n\n"
                              + MUL_TEST, {"test_mul.py": MUL_TEST,
                                           "calc.py": MUL_STUB}),
                          say("FAILS: ImportError: cannot import name 'mul'"
                              " from 'calc'\nTEST: test_mul.py\n\n" + MUL_TEST,
                              {"test_mul.py": MUL_TEST, "calc.py": ADD_ONLY})],
            "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
            "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("build-feature", "escalated-resume"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": MUL_SPEC},
        "args": ["--task", FEATURE], "ends": ["parked", "done"],
        "legs": [[], ["--resume", LAST, "--answer",
                      "keep: return the product as it is"]],
        "answers": {
            "planner.md": [MUL_PLAN, MUL_ESCALATES],
            "tester.md": [MUL_RED],
            "worker.md": [MUL_NEEDS, say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
            "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("build-feature", "wrong-test"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": MUL_SPEC},
        "args": ["--task", FEATURE], "ends": ["done"], "answers": {
            "planner.md": [MUL_PLAN],
            "tester.md": [MUL_BAD_RED, MUL_RED],
            "worker.md": [MUL_WRONG, say(MUL_BUILT, {"calc.py": WITH_MUL})],
            "reviewer.md": ["VERDICT: ok\n\n" + MUL_BUILT],
            "reviewer-runs.md": ["VERDICT: ok\n\n" + MUL_BUILT]}},
    ("build-feature", "redo-stuck"): {
        "place": {"calc.py": ADD_ONLY},
        "args": ["--task", FEATURE], "ends": ["parked"], "answers": {
            "planner.md": [MUL_PLAN],
            "tester.md": [MUL_RED],
            "worker.md": [say(MUL_BUILT, {"calc.py": WITH_MUL})] * 2,
            "reviewer.md": [MUL_REDO]}},
    ("build-feature", "spec-rewrite"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": MUL_SPEC},
        "args": ["--task", FEATURE], "ends": ["parked"], "answers": {
            "planner.md": [MUL_PLAN],
            "tester.md": [MUL_RED],
            "worker.md": [say(MUL_BUILT + "- TASK.md: says mul rounds\n",
                              {"calc.py": WITH_MUL, "TASK.md": MUL_ROUNDED})]}},
    ("build-feature", "refused"): {
        "place": {"calc.py": ADD_ONLY, "TASK.md": ADD_SPEC},
        "args": ["--task", FEATURE], "ends": ["declined"],
        "answers": {"planner.md": [MUL_DECLINES]}},
    ("fix-with-test", "wrong-test"): {
        "place": {"calc.py": BUGGY, "TASK.md": CALC_SPEC},
        "args": ["--task", BUG], "task": BUG, "ends": ["done"], "answers": {
            "worker.md": FIXES["worker.md"] * 2,
            "patcher.md": [WRONG_ADD] + FIXES["patcher.md"]}},
    ("fix-with-test", "wrong-start-test"): {
        "place": {"calc.py": BUGGY, "TASK.md": CALC_SPEC,
                  "test_old.py": OLD_TEST},
        "args": ["--task", BUG], "task": BUG, "ends": ["parked"], "answers": {
            "worker.md": FIXES["worker.md"],
            "patcher.md": [WRONG_OLD]}},
    ("fix-with-test", "refused"): {
        "place": {"calc.py": BUGGY, "TASK.md": SUB_SPEC},
        "args": ["--task", BUG], "task": BUG, "ends": ["declined"],
        "answers": {"worker.md": [ADD_DECLINES]}},
    ("fix-with-test", "conflict"): {
        "place": {"calc.py": BUGGY, "TASK.md": SUB_SPEC},
        "args": ["--task", BUG], "task": BUG, "ends": ["conflict"],
        "answers": {"worker.md": FIXES["worker.md"],
                    "patcher.md": [SUB_CONFLICT]}},
}


def shipped():
    return sorted(p.name for p in FLOWS.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))


def spec_of(flow):
    return yaml.safe_load((FLOWS / flow / "flow.yaml").read_bytes())


def calls_in(answers):
    return sum(len(a) if isinstance(a, list)
               else sum(len(v) for v in a.values()) for a in answers.values())


def steered(answer):
    """-> `answer`, leaving an instruction file in the place as well."""
    if isinstance(answer, str):
        answer = say(answer)
    return dict(answer, writes=dict(answer["writes"], **STEERED))


def ending(flow, ends, first=(), rest=False, swap=None, place=None, args=(),
           legs=None):
    """-> a case built on the flow's pass case: its place, task and args,
    the first step answering `first` and then, when `rest` says the run goes
    on, what it answers on the pass path; `swap` puts other steps' answers
    in place of the pass ones. `ends` is where every leg has to end."""
    base = CASES[(flow, "pass")]
    step = next(iter(base["answers"]))
    answers = dict(base["answers"]) if rest else {}
    answers[step] = list(first) + (list(base["answers"][step]) if rest else [])
    answers.update(swap or {})
    case = {"answers": answers, "ends": sorted(ends),
            "place": dict(base.get("place") or {}, **(place or {})),
            "args": list(base.get("args", [])) + list(args)}
    if base.get("task"):
        case["task"] = base["task"]
    if legs:
        case["legs"] = legs
    return case


def stops_of(flow):
    """-> {path: case} for every way a run of `flow` ends short that the
    runner can reach from its pass path, each at the first step that can
    reach it, carried on to the end where a resume is possible."""
    spec = spec_of(flow)
    first = CASES[(flow, "pass")]["answers"]
    opening = next(iter(first.values()))
    resumes = spec.get("journal", True)
    calls = str(calls_in(first))
    goes = settings.get("retries", flow=spec)
    out = {
        "no-answer": ending(flow, [stops.NO_ANSWER], [say("")] * goes),
        "tool-fault": ending(flow, [stops.EXCEPTION], [fatal()]),
        "interrupted": ending(flow, [stops.INTERRUPT], [INTERRUPTED]),
        "guard-refused": ending(flow, [stops.REFUSED], [steered(opening[0])]),
        "refused": ending(flow, [stops.DECLINED], [DECLINES],
                          place={"notes.md": NOTES_MD}),
        "conflict": ending(flow, [stops.CONFLICT], [RULE_CONFLICT],
                           place={"RULES.md": RULES}),
        "no-verdict": ending(flow, [stops.GATE], rest=True,
                             swap={"reviewer.md": [NO_VERDICT]})}
    fans = [s["prompt"] for s in spec["steps"] if s.get("fanout")]
    if fans:
        tasks = first[fans[0]]
        # tasks naming one file run in turn, so which one wrote the stray
        # file is known; side by side, either could have
        plan = [opening[0].replace("FILES:\n", "FILES:\n- shared.md\n")]
        out["overlap"] = ending(flow, [stops.OVERLAP], plan, swap={
            fans[0]: {**tasks, 1: [say(tasks[1][0], {
                "stray.md": "a file no task named\n"})]}})
    if resumes:
        out["ruling-resume"] = ending(
            flow, [stops.PARKED, stops.DONE], [ASKS_WHO], rest=True,
            legs=[[], ["--resume", LAST, "--answer", "no: leave names out"]])
        out["outage-resume"] = ending(
            flow, [stops.OUTAGE, stops.DONE], [limited()], rest=True,
            legs=[[], ["--resume", LAST]])
        out["capped-resume"] = ending(
            flow, [stops.BUDGET, stops.DONE], rest=True,
            legs=[["--max-calls", "1"], ["--resume", LAST, "--max-calls", calls]])
    else:
        out["ruling"] = ending(flow, [stops.PARKED], [ASKS_WHO])
        out["outage"] = ending(flow, [stops.OUTAGE], [limited()])
        out["capped"] = ending(flow, [stops.BUDGET], opening,
                               args=["--max-calls", "1"])
    return out


# a stop path a golden under another name already reaches
PINNED_AS = {("fix-with-test", "outage-resume"): "chained-resume",
             ("build-feature", "ruling-resume"): "escalated-resume"}

for _flow in shipped():
    for _path, _case in stops_of(_flow).items():
        if (_flow, _path) in CASES or (_flow, _path) in PINNED_AS:
            continue
        if _path == "no-verdict" and (_flow, "gate-fail") in CASES:
            continue
        CASES[(_flow, _path)] = _case


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
        if answer.get("raise"):
            raise answer["raise"]()
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
    real_ask = retro.ask

    def ask(run, text, used):
        script.asking(retro.STEP, None)
        return real_ask(run, text, used)

    monkeypatch.setattr(retro, "ask", ask)
    # a go that failed waits before the next; a replay has nothing to wait for
    real_retry = engine.retry
    monkeypatch.setattr(engine, "retry", lambda fn, cap=3, sleep=None:
                        real_retry(fn, cap, sleep=lambda secs: None))
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
            monkeypatch.setattr("agentweft.runner.begin.datetime", clock)
            monkeypatch.setattr("agentweft.runner.ending.datetime", clock)
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
    # and an earlier leg's "- patcher.md in leg 1 0.2s ($0.0000)"
    (re.compile(r"(\.md in leg \d+ )\d+(\.\d+)?s(?= \()"), r"\1<secs>s"),
    # the retro's "- won none: 3 passes, 4.2s, $0.0300"
    (re.compile(r"(?<=pass, )\d+(\.\d+)?s(?=, \$)"), "<secs>s"),
    (re.compile(r"(?<=passes, )\d+(\.\d+)?s(?=, \$)"), "<secs>s"),
    # pytest's own run time, in the output tail a failed command gate quotes
    (re.compile(r"\b((?:passed|failed|errors?|skipped) in )\d+(\.\d+)?s\b"),
     r"\1<secs>s"),
    # the retro's "- wall 4.2s: steps 3.1s, gates 0.6s, runner 0.5s"; fanned
    # tasks that ran at once can sum past the wall, a matter of timing only
    (re.compile(r"(?<=^- wall )\d+(\.\d+)?s: steps \d+(\.\d+)?s, gates"
                r" \d+(\.\d+)?s, runner \d+(\.\d+)?s$", re.M),
     "<secs>s: steps <secs>s, gates <secs>s, runner <secs>s"),
    (re.compile(r"(?<=^- wall )\d+(\.\d+)?s: steps \d+(\.\d+)?s summed, past"
                r" the wall because fanned tasks ran side by side, gates"
                r" \d+(\.\d+)?s$", re.M),
     "<secs>s: steps <secs>s, gates <secs>s, runner <secs>s"),
    # the handoff's chain head hashes lines that carry the time
    (re.compile(r"(?<=lines, head )[0-9a-f]{16}"), "<hash>"),
)
CLOCKED = ("time", "seconds")
# a line's chain hashes the line before it, clock and run id included
HASHED = ("chain",)


def hashes_out(value):
    if isinstance(value, dict):
        return {k: hashes_out(v) for k, v in value.items()}
    return "<hash>" if isinstance(value, str) else value


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
                    else hashes_out(v) if k in HASHED
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


def changed(was, now):
    return [l for l in difflib.unified_diff(
        was.split("\n"), now.split("\n"), lineterm="", n=0)
        if not l.startswith(("---", "+++", "@@"))]


def settle(flow, path, got, names, said):
    """compares when `names` is None, else writes a missing golden and
    rewrites an existing one only when `names` holds flow/path."""
    target = golden_file(flow, path)
    name = flow + "/" + path
    if names is None:
        return compare(flow, path, got, False)
    if not target.exists():
        compare(flow, path, got, True)
        said.append("wrote " + name)
        return
    lines = changed(dump(json.loads(target.read_bytes().decode("utf-8"))),
                    dump(got))
    if name in names:
        if not lines:
            said.append(name + " already matches")
            return
        compare(flow, path, got, True)
        said.extend(["rewrote " + name] + lines)
        return
    if lines:
        pytest.fail("\n".join(lines + [
            name + " differs from its golden, left as it was. "
            "--update-golden " + name + " rewrites it"]), pytrace=False)


@pytest.mark.parametrize("flow,path", sorted(CASES),
                         ids=[f + "/" + p for f, p in sorted(CASES)])
def test_a_shipped_flow_does_what_its_golden_says(flow, path, tmp_path,
                                                  monkeypatch, capsys,
                                                  update_golden, golden_said):
    got = replay(flow, CASES[(flow, path)], tmp_path, monkeypatch, capsys)
    if CASES[(flow, path)].get("ends"):
        # a stop case is there for where it ends, so the golden has to end
        # there, under the outcome word the runner gives that cause
        ends = ends_of(got)
        assert ends == set(CASES[(flow, path)]["ends"])
        heads = [line for line in got["handoff"] if HEAD.match(line)]
        for cause in ends - {stops.DONE}:
            assert any(stops.outcome(cause) in h for h in heads), cause
    settle(flow, path, got, update_golden, golden_said)


def test_every_shipped_flow_has_its_pass_path_pinned():
    assert sorted(f for f, p in CASES if p == "pass") == shipped()


ENDS = (stops.DONE,) + stops.CAUSES
HEAD = re.compile(r"^# .+?: (.+)$")


def cannot(flow):
    """-> {end: why} for the ends a replay of `flow` as shipped cannot
    reach. kept by name, so a cause added to the runner is not on it and
    turns the suite red until a golden reaches it or a reason is written
    here."""
    spec = spec_of(flow)
    out = {
        # the sign-off checks a merge only in a git work tree, and a
        # replay's place is a plain folder
        stops.MOVED: "a replay's place is not a git work tree",
        stops.UNCHECKED: "a replay's place is not a git work tree"}
    if not any(s.get("fanout") for s in spec["steps"]):
        out[stops.OVERLAP] = "the flow has no fanned-out step"
    if spec.get("police") not in (True, "on"):
        out[stops.OFF_TASK] = "the flow does not turn the police on"
    return out


def ends_of(got):
    """-> the ends a replay reached, one per leg: each stop's cause off its
    step line, and `done` for a leg whose handoff says so."""
    out = set(s["cause"] for s in got["steps"] if s.get("cause"))
    for line in got["handoff"]:
        head = HEAD.match(line)
        if head and head.group(1).startswith(stops.DONE):
            out.add(stops.DONE)
    return out


def pinned():
    """-> {flow: the ends its goldens reach}, read off the files."""
    out = {}
    for path in GOLDEN.glob("*/*.json"):
        out.setdefault(path.parent.name, set()).update(
            ends_of(json.loads(path.read_bytes().decode("utf-8"))))
    return out


def test_every_end_path_of_a_shipped_flow_is_pinned_by_a_golden():
    have = pinned()
    missing = [flow + ": " + end for flow in shipped() for end in ENDS
               if end not in have.get(flow, set()) and end not in cannot(flow)]
    assert missing == [], ("no golden ends on these: "
                           + ", ".join(missing))


def test_an_end_said_to_be_out_of_reach_is_reached_by_no_golden():
    have = pinned()
    reached = [flow + ": " + end for flow in shipped()
               for end in cannot(flow) if end in have.get(flow, set())]
    assert reached == []


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
    monkeypatch.setattr("agentweft.runner.begin.datetime", clock)
    monkeypatch.setattr("agentweft.runner.ending.datetime", clock)
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
           "run": "flow-2026-01-02-030405",
           "chain": {"prev": "ab" * 32, "files": {"red-proof.json": None}}}
    two = {"time": "2027-11-30T23:59:59", "seconds": 0.0,
           "why": (tmp_path / "place" / "a.py").as_posix()
           + " at 2027-11-30 23:59",
           "line": "2027-11-30 23:59  flow  ok  0s  flow-2027-11-30-1.md",
           "run": "flow-2027-11-30-235959",
           "chain": {"prev": "cd" * 32, "files": {"red-proof.json": None}}}
    assert normalise(one, tmp_path) == normalise(two, tmp_path)
    assert normalise(one, tmp_path)["chain"] == {
        "prev": "<hash>", "files": {"red-proof.json": None}}
    assert normalise(one, tmp_path)["why"] == "<tmp>/place/a.py at <time>"


def test_the_retro_line_of_an_earlier_leg_has_its_seconds_taken_out(tmp_path):
    def retro(secs):
        return {"handoff": ["- patcher.md in leg 1 " + secs + " ($0.0000), won"
                            " none: limit events 1",
                            "- worker.md in leg 12 " + secs + " ($0.0100)"]}

    assert normalise(retro("0.2s"), tmp_path) == normalise(retro("0s"),
                                                           tmp_path)
    assert normalise(retro("0.2s"), tmp_path)["handoff"][0].startswith(
        "- patcher.md in leg 1 <secs>s ($0.0000)")


def a_golden(tmp_path, monkeypatch, value):
    monkeypatch.setattr(sys.modules[__name__], "GOLDEN", tmp_path / "golden")
    target = golden_file("some-flow", "pass")
    if value is not None:
        target.parent.mkdir(parents=True)
        target.write_bytes(dump(value).encode("utf-8"))
    return target


def test_an_existing_golden_that_differs_is_left_as_it_was_unless_named(
        tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, {"exit": 0, "path": ["1 a"]})
    before = target.read_bytes()
    said = []
    with pytest.raises(pytest.fail.Exception) as failed:
        settle("some-flow", "pass", {"exit": 1, "path": ["1 a"]},
               frozenset(), said)
    assert target.read_bytes() == before
    assert '-  "exit": 0,' in str(failed.value)
    assert '+  "exit": 1,' in str(failed.value)
    assert '"path"' not in str(failed.value)
    assert "--update-golden some-flow/pass" in str(failed.value)
    assert said == []


def test_a_golden_checked_out_with_crlf_line_ends_matches_its_value(
        tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, None)
    target.parent.mkdir(parents=True)
    value = {"exit": 0, "path": ["1 a"]}
    target.write_bytes(dump(value).replace("\n", "\r\n").encode("utf-8"))
    before = target.read_bytes()
    said = []
    settle("some-flow", "pass", value, frozenset(), said)
    settle("some-flow", "pass", value, frozenset({"some-flow/pass"}), said)
    assert target.read_bytes() == before
    assert said == ["some-flow/pass already matches"]


def test_a_golden_that_is_named_is_rewritten_and_its_change_said(
        tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, {"exit": 0, "path": ["1 a"]})
    said = []
    settle("some-flow", "pass", {"exit": 1, "path": ["1 a"]},
           frozenset({"some-flow/pass", "other/pass"}), said)
    assert target.read_bytes() == dump({"exit": 1, "path": ["1 a"]}).encode()
    assert said[0] == "rewrote some-flow/pass"
    assert '-  "exit": 0,' in said
    assert '+  "exit": 1,' in said


def test_a_named_golden_that_already_matches_is_left_as_it_was(
        tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, {"exit": 0})
    before = target.read_bytes()
    said = []
    settle("some-flow", "pass", {"exit": 0},
           frozenset({"some-flow/pass"}), said)
    assert target.read_bytes() == before
    assert said == ["some-flow/pass already matches"]


def test_a_missing_golden_is_written_without_being_named(
        tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, None)
    said = []
    settle("some-flow", "pass", {"exit": 0}, frozenset(), said)
    assert target.read_bytes() == dump({"exit": 0}).encode()
    assert said == ["wrote some-flow/pass"]


def test_without_the_option_a_golden_is_only_compared(tmp_path, monkeypatch):
    target = a_golden(tmp_path, monkeypatch, {"exit": 0})
    before = target.read_bytes()
    with pytest.raises(AssertionError):
        settle("some-flow", "pass", {"exit": 1}, None, [])
    assert target.read_bytes() == before


@pytest.mark.parametrize("given,names", [
    (None, None),
    ([""], frozenset()),
    (["a/pass"], frozenset({"a/pass"})),
    (["a/pass,b/redo", "", "c/pass"], frozenset({"a/pass", "b/redo",
                                                  "c/pass"})),
    ([" a/pass , b/redo,"], frozenset({"a/pass", "b/redo"})),
], ids=["absent", "bare", "one", "repeated-and-comma", "spaced"])
def test_the_update_option_reads_as_the_goldens_it_names(given, names):
    assert golden_names(given) == names


def test_a_name_with_no_golden_behind_it_is_refused(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "pass.json").write_text("{}\n")
    assert unknown_goldens(frozenset({"a/pass"}), tmp_path) == []
    assert unknown_goldens(frozenset({"a/pass", "a/redo",
                                      "tests/test_golden.py"}),
                           tmp_path) == ["a/redo", "tests/test_golden.py"]
