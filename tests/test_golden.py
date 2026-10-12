"""what each shipped flow does, path by path, held against tests/golden/.

a replay runs the real `main()` over a shipped flow with the cli provider
answering from a script instead of a process, and keeps what a person or the
next run reads: the steps it took and where each one sent the work, every
gate, the journal and index lines, the handoff, the files left behind and
what it printed. times, run ids, seconds and the temp place are taken out
first, so the same run on another day, machine or OS reads the same.

`python -m pytest tests/test_golden.py --update-golden` rewrites the files.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, ".")
from agentweft.providers import cli_provider
from agentweft.runner import engine, prompts, trace

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
REPO = HERE.parent
FLOWS = REPO / "flows"
TEST_FLOWS = HERE / "flows"
MODEL = "model-in-replay"


def say(text, writes=None):
    """an answer that also leaves files in the place, the way a model run
    there edits them."""
    return {"say": text, "writes": writes or {}}


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

CASES = {
    ("code-review", "pass"): {"answers": {
        "worker.md": [ONE_FINDING],
        "reviewer.md": ["VERDICT: ok\n\n" + ONE_FINDING]}},
    ("code-review", "redo"): {"answers": {
        "worker.md": ["- [high] app.py the loop reads one past the end\n",
                      ONE_FINDING],
        "reviewer.md": ["VERDICT: redo\n\nthe finding on app.py has no line\n",
                        "VERDICT: ok\n\n" + ONE_FINDING]}},
    ("fix-with-test", "pass"): {"place": {"calc.py": BUGGY}, "answers": {
        "worker.md": [say("FAILS: assert -1 == 3\nTEST: test_calc.py\n\n"
                          + TEST, {"test_calc.py": TEST})],
        "patcher.md": [say("TEST: test_calc.py\n\n-    return a - b\n"
                           "+    total = a + b\n+    return total\n",
                           {"calc.py": FIXED})],
        "verify.md": ["PASS the test is written before the patch\n"
                      "PASS the test fails on the unpatched code\n"
                      "PASS the patch is the smallest thing that turns it "
                      "green\n"]}},
    ("fix-with-test", "gate-fail"): {"place": {"calc.py": BUGGY}, "answers": {
        "worker.md": ["could not make it fail: add(1, 2) looks right to me\n"]}},
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
        "worker.md": {1: ["app.py parses argv and calls run().\n"],
                      2: ["config.py loads settings.yml, no defaults.\n"]},
        "merge.md": [AUDIT],
        "reviewer.md": ["VERDICT: redo\n\nconfig.py: which settings were "
                        "read is not said\n"]}},
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
        "reviewer.md": ["VERDICT: ok\n\nhere is your digest\n\n" + DIGEST]}},
    ("weekly-digest", "redo"): {"answers": {
        "planner.md": [DIGEST_PLAN],
        "worker.md": {1: ["- notes.md: the plan moved to friday\n"],
                      2: ["- rent.md: due on the 1st\n"]},
        "merge.md": [DIGEST],
        "reviewer.md": ["VERDICT: redo\n\ngarden.md was never in the plan\n"]}},
    ("risky-edit", "hot-park"): {
        "flows": TEST_FLOWS,
        "ranking": "src/hooks.ts 0.94\nsrc/util.ts 0.11\n",
        "answers": {
            "planner.md": ["src/hooks.ts: the retry loop lives there\n"],
            "worker.md": ["edited src/hooks.ts: the retry loop backs off "
                          "before the third call\n"]}},
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
        self.lock = threading.Lock()
        self.now = threading.local()

    def asking(self, step, task):
        self.now.step, self.now.task = step, task

    def run(self, argv, **kw):
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
    monkeypatch.setattr(engine, "CACHE", {})
    monkeypatch.setattr(sys, "argv", ["run.py", flow, "--force"])
    for key in list(os.environ):
        if key.startswith("MODEL_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("MODEL", MODEL)
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

    def step(self, name, previous=engine.EMPTY, extra="", task=None):
        script.asking(name, task)
        return real_step(self, name, previous=previous, extra=extra, task=task)

    monkeypatch.setattr(engine.Run, "step", step)
    monkeypatch.setattr(cli_provider, "subprocess", types.SimpleNamespace(
        run=script.run, TimeoutExpired=subprocess.TimeoutExpired))

    capsys.readouterr()
    raised = None
    code = None
    try:
        code = engine.main()
    except Exception as e:
        raised = type(e).__name__ + ": " + str(e)
    printed = capsys.readouterr().out
    assert script.unused() == [], "answers the run never asked for"
    return normalise(record(tmp_path / "runs", code, raised, printed),
                     tmp_path)


def text_lines(path):
    if not path.exists():
        return []
    return [l for l in path.read_bytes().decode("utf-8").replace("\r\n", "\n")
            .split("\n") if l.strip()]


def record(runs, code, raised, printed):
    steps = []
    handoff = []
    for folder in sorted(p for p in runs.iterdir() if p.is_dir()):
        steps = steps + [json.loads(l) for l in text_lines(folder / trace.FILE)]
        handoff = handoff + text_lines(folder / "handoff.md")
    return {
        "exit": code,
        "raised": raised,
        "path": [str(l["seq"]) + " " + l["step"] + " " + l["outcome"]
                 + (" -> " + l["to"] if l["to"] else "")
                 + "".join(("  PASS " if g["ok"] else "  FAIL ") + g["gate"]
                           for g in l["gates"])
                 for l in steps],
        "journal": text_lines(runs / "journal.md"),
        "index": text_lines(runs / "index.md"),
        "handoff": handoff,
        "files": sorted(p.relative_to(runs).as_posix()
                        for p in runs.rglob("*") if p.is_file()),
        "steps": steps,
        "printed": [l.rstrip() for l in printed.replace("\r\n", "\n")
                    .split("\n") if l.strip()],
    }


STAMPS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}"), "<run>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?"), "<time>"),
    (re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"), "<time>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<day>"),
    # the journal's run time and the handoff's per-step seconds
    (re.compile(r"(?<=  )\d+s(?=  |$)"), "<secs>s"),
    (re.compile(r"(?m)^(  \S+ +)\d+(\.\d+)?s$"), r"\1<secs>s"),
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
    for where, name in ((tmp_path, "<tmp>"), (REPO, "<repo>")):
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


SHIFT = datetime.timedelta(days=400, hours=13, minutes=17)


class Later(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.datetime.now(tz) + SHIFT


class LaterDay(datetime.date):
    @classmethod
    def today(cls):
        return (datetime.datetime.now() + SHIFT).date()


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
