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
      kind: convention            or a list, any one of them
      label: important            when given, the fact's label (optional)
    ticket:
      file: README.md             the one file the nice-to-do ticket is on
      claim: [--output]           words its claim holds, all

a case names the items it is scored on: a run with a failed attempt the
first four, a run that left a doc stale the ticket, a run whose lead ruled
the fact. an answer scores one for each; the fact and the ticket only when
the runner would write them on the case's record (an edit or a test guard
counts as the ticket the runner would keep it as). a change sent to the wrong
file is worth nothing whatever else it got right, so it scores 0. a blind
reader gives the change text and the fact's why 0 to 2 apart (`reader`, None
until then). a case passes a cell when every repeat scores all its items.

`python -m agentweft.bench --retro <folder>` asks the retro role alone on
each case's record (step mode) with the provider in `<folder>/bench.yaml`,
k times, and scores each answer, with what it cost, its tokens and the
seconds it took.
"""
import datetime
import json
import re
import shutil
import tempfile
import time
import types
from pathlib import Path

import yaml

from agentweft.guardrails import factsguard, retroedits
from agentweft.orchestrate import decisions, facts
from agentweft.runner import retro, trace, upkeep

GOLD = "gold.yaml"
ANSWER = "gold.md"
ITEMS = ("failed", "cause", "change", "fact", "ticket")
# the items a case with a failed attempt is scored on
FAILED = ("failed", "cause", "change")
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


def prompt_of(case, view=None):
    """-> what a run hands the retro for this record: the same prompt, the
    same parts, in the same order. `view` is the record's copy without the
    steps' reasons (`retro.view`) the prompt points at."""
    case = Path(case)
    record = case / "record"
    gold = gold_of(case)
    trail = types.SimpleNamespace(
        folder=record, closed=[(types.SimpleNamespace(written=l), None)
                               for l in lines_of(record)])
    looked = retro.recorded(trail)
    changed = changed_in(record)
    gone, put = retroedits.names_of(diff_of(record))
    docs = retroedits.named(case / "place", changed, gone + put) \
        if changed else []
    return retro.prompt(gold.get("run", case.name), gold.get("flow", ""),
                        gold.get("outcome", "done"), record,
                        retro.whys(trail), retro.issues(looked),
                        retro.workarounds(looked),
                        retro.parts(looked, ["- none"], changed, [], [],
                                    factsguard.CAP, docs), record=view)


def diff_of(record):
    path = Path(record) / "diff.patch"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


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


def record_of(case, place):
    """-> the Record a run holds for the case: the place, the (command, exit
    code) of each gate line in record/steps.jsonl that names its command,
    and the rulings in the place's decisions.md."""
    ran = []
    for line in lines_of(Path(case) / "record"):
        for g in line.get("gates") or []:
            m = retro.EXIT.search(str(g.get("detail") or "")) \
                if isinstance(g, dict) and g.get("command") else None
            if m:
                ran.append((g["command"] if isinstance(g["command"], str)
                            else " ".join(g["command"]), int(m.group(1))))
    try:
        stamps = [d.at.strftime(decisions.STAMP)
                  for d in decisions.read(place)]
    except (OSError, ValueError, AttributeError):
        stamps = []
    return factsguard.Record(place, ran=ran, stamps=stamps)


def refusal(case, verb, value, fields):
    """-> why the runner would not write the proposed fact on the case's
    record, "" when it would: held to a copy of place/, so nothing in the
    case is touched."""
    with tempfile.TemporaryDirectory(prefix="retro-gold-",
                                     ignore_cleanup_errors=True) as tmp:
        place = Path(tmp) / "place"
        shutil.copytree(str(Path(case) / "place"), str(place))
        given = dict(fields, supersedes=value) if verb == "supersede" \
            else fields
        return factsguard.Store(place).refusal(factsguard.Proposal(given),
                                               record_of(case, place))


def ticket_of(case, verb, value, fields):
    """-> the fields of the nice-to-do ticket an item is, or None: a
    nice-to-do fact as it stands, an edit or a test guard as the runner
    would keep it (`upkeep.ticket_of`), anything else none."""
    if verb == "fact":
        return fields if fields.get("kind") == facts.NICE else None
    if verb in upkeep.EDITS or verb == "guard" \
            and fields.get("kind", "").strip() == "test":
        return upkeep.ticket_of(Path(case) / "place", verb, value, fields)[0]
    return None


def items_of(gold):
    """-> the items a case is scored on, in order."""
    return [i for i in ITEMS if i in gold
            or i in FAILED and "failed" in gold]


def score(answer, gold, case):
    """-> one per item the case names (0 or 1), `score` out of them,
    `passed`, and `reader` left for the blind reader. the fact point needs a
    fact the runner would write, and the ticket point a nice-to-do ticket it
    would keep, on the case's record, `case` its folder."""
    names = items_of(gold)
    got = dict.fromkeys(names, 0)
    if "failed" in gold:
        seq, step = gold["failed"].split()[1:3]
        found = sections(answer).get((int(seq), step))
        if found is not None:
            got["failed"] = 1
            why = (found.get("why") or "").lower()
            got["cause"] = int(all(w.lower() in why for w in gold["cause"]))
            got["change"] = int(path_form(gold["change"])
                                in path_form(found.get("change")))
    items, _ = upkeep.parse(answer)
    if "fact" in gold:
        wanted = {path_form(s).rstrip("/") for s in gold["fact"]["scope"]}
        kinds = gold["fact"]["kind"]
        kinds = [kinds] if isinstance(kinds, str) else list(kinds)
        for verb, value, fields in items or []:
            scopes = {path_form(s).rstrip("/")
                      for s in fields.get("scope") or []}
            if verb in ("fact", "supersede") and scopes & wanted \
                    and fields.get("kind") in kinds \
                    and ("label" not in gold["fact"]
                         or fields.get("label") == gold["fact"]["label"]) \
                    and not refusal(case, verb, value, fields):
                got["fact"] = 1
    if "ticket" in gold:
        want = gold["ticket"]
        for verb, value, fields in items or []:
            ticket = ticket_of(case, verb, value, fields)
            if ticket is not None \
                    and [path_form(s) for s in ticket.get("scope") or []] \
                    == [path_form(want["file"])] \
                    and all(w in (ticket.get("claim") or "")
                            for w in want["claim"]) \
                    and not refusal(case, "fact", None, ticket):
                got["ticket"] = 1
    total = sum(got.values()) if got.get("change", 1) else 0
    return dict(got, score=total, passed=total == len(names), reader=None)


def ask(provider, case):
    """-> (the retro role's answer on the case's record, asked alone in the
    case's place, what it cost, its tokens as a step's line counts them,
    the seconds it took)."""
    provider.where = str(Path(case) / "place")
    provider.at(retro.STEP, None)
    with tempfile.TemporaryDirectory(prefix="agentweft-retro-view-") as tmp:
        text = prompt_of(case, retro.view(Path(case) / "record", tmp))
        began = time.time()
        reply = provider.ask(text)
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
            names = items_of(gold_of(case))
            got = score(text, gold_of(case), case)
            rows.append(dict(got, case=case.name, k=n, cost=cost,
                             tokens=tokens, seconds=seconds, answer=text))
            said(case.name + " k" + str(n) + ": " + str(got["score"])
                 + " of " + str(len(names))
                 + ("" if got["passed"] else ", "
                    + ", ".join(i for i in names if not got[i])
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
