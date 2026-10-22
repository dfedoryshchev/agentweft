"""the retro held to a gold.

a case is a folder: `record/` is a run as the runner wrote it (steps.jsonl,
handoff.md, the diff), `place/` the project as the run left it, `gold.md` the
answer a careful reader writes for that record, and `gold.yaml` what the
program checks it on:

    failed: seq 3 worker.md       the attempt that failed, by seq and step
    cause: [reader.py, print]     words the section's why line holds, all
    change: pkg/reader.py         the file the section's change line names
    fact:
      scope: [pkg/]               one of these among the fact's scopes
      kind: convention

an answer scores one for each of the four. a change sent to the wrong file
is worth nothing whatever else it got right, so it scores 0. a blind reader
gives the change text and the fact's why 0 to 2 apart (`reader`, None until
then). a case passes a cell when every repeat scores 4.

`python -m agentweft.bench --retro <folder>` asks the retro role alone on
each case's record (step mode) with the provider in `<folder>/bench.yaml`,
k times, and scores each answer, with what it cost, its tokens and the
seconds it took.
"""
import datetime
import json
import re
import time
import types
from pathlib import Path

import yaml

from agentweft.guardrails import factsguard
from agentweft.runner import retro, trace, upkeep

GOLD = "gold.yaml"
ANSWER = "gold.md"
ITEMS = ("failed", "cause", "change", "fact")
SECTION = re.compile(r"^##\s+seq\s+(\d+)\s+(\S+)\s*$")
FIELD = re.compile(r"^(failed|why|change)\s*:\s*(.*?)\s*$")


def cases(folder):
    """-> each case folder under `folder`, by name."""
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_dir() and (p / GOLD).is_file())


def gold_of(case):
    return yaml.safe_load((Path(case) / GOLD).read_text(encoding="utf-8"))


def answer_of(case):
    return (Path(case) / ANSWER).read_text(encoding="utf-8")


def lines_of(record):
    out = []
    path = Path(record) / "steps.jsonl"
    for raw in path.read_text(encoding="utf-8").split("\n"):
        if raw.strip():
            out.append(json.loads(raw))
    return out


def changed_in(record):
    """-> the paths the record's diff names, in its order."""
    path = Path(record) / "diff.patch"
    if not path.is_file():
        return None
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("+++ b/") and line[6:] not in out:
            out.append(line[6:])
    return out


def prompt_of(case):
    """-> what a run hands the retro for this record: the same prompt, the
    same parts, in the same order."""
    case = Path(case)
    record = case / "record"
    gold = gold_of(case)
    trail = types.SimpleNamespace(
        folder=record, closed=[(types.SimpleNamespace(written=l), None)
                               for l in lines_of(record)])
    looked = retro.recorded(trail)
    return retro.prompt(gold.get("run", case.name), gold.get("flow", ""),
                        gold.get("outcome", "done"), record,
                        retro.whys(trail), retro.issues(looked),
                        retro.workarounds(looked),
                        retro.parts(looked, ["- none"], changed_in(record),
                                    [], [], factsguard.CAP))


def sections(answer):
    """-> {(seq, step): {failed, why, change}} for each `## seq` section."""
    out = {}
    now = None
    for line in (answer or "").replace("\r\n", "\n").split("\n"):
        head = SECTION.match(line.strip())
        if head:
            now = out.setdefault((int(head.group(1)), head.group(2)), {})
            continue
        if line.startswith("## "):
            now = None
            continue
        field = FIELD.match(line.strip())
        if field and now is not None and field.group(1) not in now:
            now[field.group(1)] = field.group(2)
    return out


def path_form(text):
    return (text or "").replace("\\", "/").strip().lower()


def score(answer, gold):
    """-> one per item (0 or 1), `score` out of 4, `passed`, and `reader`
    left for the blind reader."""
    seq, step = gold["failed"].split()[1:3]
    found = sections(answer).get((int(seq), step))
    got = dict.fromkeys(ITEMS, 0)
    if found is not None:
        got["failed"] = 1
        why = (found.get("why") or "").lower()
        got["cause"] = int(all(w.lower() in why for w in gold["cause"]))
        got["change"] = int(path_form(gold["change"])
                            in path_form(found.get("change")))
    items, _ = upkeep.parse(answer)
    wanted = {path_form(s).rstrip("/") for s in gold["fact"]["scope"]}
    for verb, _, fields in items or []:
        scopes = {path_form(s).rstrip("/") for s in fields.get("scope") or []}
        if verb in ("fact", "supersede") and scopes & wanted \
                and fields.get("kind") == gold["fact"]["kind"]:
            got["fact"] = 1
    total = sum(got.values()) if got["change"] else 0
    return dict(got, score=total, passed=total == len(ITEMS), reader=None)


def ask(provider, case):
    """-> (the retro role's answer on the case's record, asked alone in the
    case's place, what it cost, its tokens as a step's line counts them,
    the seconds it took)."""
    provider.where = str(Path(case) / "place")
    provider.at(retro.STEP, None)
    began = time.time()
    reply = provider.ask(prompt_of(case))
    seconds = round(time.time() - began, 3)
    return (reply.text or "", getattr(reply, "cost", None),
            trace.tokens([types.SimpleNamespace(replies=[reply])]), seconds)


def run(folder, block, k, said=print):
    """-> a row per case and repeat, one provider for the whole set, with
    the read grant a run gives the retro."""
    from agentweft.providers import build

    provider = build(block, grant=retro.GRANT)
    rows = []
    for case in cases(folder):
        for n in range(1, k + 1):
            text, cost, tokens, seconds = ask(provider, case)
            got = score(text, gold_of(case))
            rows.append(dict(got, case=case.name, k=n, cost=cost,
                             tokens=tokens, seconds=seconds, answer=text))
            said(case.name + " k" + str(n) + ": " + str(got["score"])
                 + " of 4" + ("" if got["passed"] else ", "
                              + ", ".join(i for i in ITEMS if not got[i])
                              + " missed"))
    return rows


def summary(rows, k):
    names = sorted({r["case"] for r in rows})
    passed = [n for n in names
              if all(r["passed"] for r in rows if r["case"] == n)
              and sum(1 for r in rows if r["case"] == n) == k]
    return {"cases": len(names), "passed": len(passed), "k": k}


def main(argv, valued, live_flag="--live", fake="fake"):
    """step mode: -> 0 when every case was asked and scored."""
    from agentweft.runner import state

    folder = Path(valued(argv, "--retro") or "")
    if not folder.is_dir():
        print(str(folder) + ": no such folder")
        return 1
    try:
        k = int(valued(argv, "--k") or 1)
    except ValueError:
        k = 0
    if k < 1:
        print("--k is at least 1")
        return 1
    conf = folder / "bench.yaml"
    block = (yaml.safe_load(conf.read_text(encoding="utf-8")) or {}).get(
        "provider") if conf.is_file() else None
    if not block:
        print("no provider: name one in " + str(conf))
        return 1
    if block.get("provider") != fake and live_flag not in argv:
        print("the retro runs on " + str(block.get("provider")) + ", which"
              " calls a real model. " + live_flag + " runs it, and it is"
              " charged")
        return 1
    if not cases(folder):
        print(str(folder) + ": no case (a folder with " + GOLD + ")")
        return 1
    rows = run(folder, block, k)
    total = summary(rows, k)
    date = datetime.datetime.now()
    out = valued(argv, "--out")
    path = Path(out) if out else (Path(state.RUNS) / "bench" / (
        "retro-" + folder.name + "-" + date.strftime("%Y%m%d-%H%M%S")
        + ".json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"set": folder.name, "provider": block,
                                "date": date.isoformat(timespec="seconds"),
                                "summary": total, "runs": rows}, indent=2),
                    encoding="utf-8")
    print(str(total["passed"]) + " of " + str(total["cases"]) + " cases passed"
          " at " + str(k) + " of " + str(k))
    print("scores: " + str(path))
    return 0
