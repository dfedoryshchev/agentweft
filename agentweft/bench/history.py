"""scores kept per commit, so one commit's can be held against another's.

every bench and eval run appends a record per task and repeat to one JSON
lines file: the commit, the flow, the task, the repeat, whether it passed,
finished without passing or stopped, the hidden score, what it cost and
whether it was replayed. compare reads two commits' records back and says,
per task, what got worse, better or stayed.
"""
import json
import math
import subprocess
from pathlib import Path

DEFAULT = Path("bench") / "scores.jsonl"
SCORES = [DEFAULT]
PASS = "pass"
FINISHED = "finished"
STOPPED = "stopped"
OUTCOMES = (PASS, FINISHED, STOPPED)
FIELDS = ("sha", "dirty", "source", "set", "flow", "task", "repeat",
          "outcome", "score", "of", "usd", "tokens", "seconds", "replayed")


def place(given=None):
    """-> where the records go. a run folder is refused: runs are cleared,
    and the records are what outlives them."""
    from agentweft.runner import state

    path = Path(given) if given else SCORES[0]
    runs = Path(state.RUNS).resolve()
    if path.resolve() == runs or runs in path.resolve().parents:
        raise ValueError(str(path) + " is inside " + str(runs) + ", which is "
                         "cleared with the runs. keep the scores elsewhere")
    return path


def git(*args):
    try:
        done = subprocess.run(["git"] + list(args), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def commit(scores=None):
    """-> (HEAD's sha, whether a tracked file differs from it), or (None,
    False) outside a git tree."""
    sha = git("rev-parse", "HEAD")
    top = git("rev-parse", "--show-toplevel")
    changed = git("diff", "--name-only", "-z", "HEAD")
    if not sha or top is None or changed is None:
        return None, False
    # the scores file is left out, or keeping one score would mark the next
    # as made on uncommitted changes
    mine = Path(scores or SCORES[0]).resolve()
    dirty = any((Path(top.strip()) / n).resolve() != mine
                for n in changed.split("\0") if n)
    return sha.strip(), dirty


def ancestors(sha):
    """-> `sha` and the commits before it, nearest first, or [] when git
    does not know it."""
    out = git("rev-list", "--max-count=1000", sha)
    return out.split() if out else []


def made(sha, dirty, source, name, flow, task, repeat, outcome, score, of,
         usd, tokens, seconds, replayed):
    return dict(zip(FIELDS, (sha, dirty, source, name, flow, task, repeat,
                             outcome, score, of, usd, tokens, seconds,
                             replayed)))


def from_bench(sha, dirty, flow, name, rows):
    out = []
    for r in rows:
        h = r["hidden"]
        word = PASS if r["core_correct"] else (
            FINISHED if r["finished"] else STOPPED)
        out.append(made(sha, dirty, "bench", name, flow, r["task"],
                        r["attempt"], word, h["cases"] - len(h["red"]),
                        h["cases"], r["usd"], r["tokens"], r["wall"], False))
    return out


def from_evals(sha, dirty, flow, results):
    out = []
    for name, r in results:
        word = PASS if r["passed"] == r["checked"] else (
            STOPPED if r.get("stopped") else FINISHED)
        out.append(made(sha, dirty, "eval", None, flow, name, 1, word,
                        r["passed"], r["checked"], r.get("usd"), r["tokens"],
                        r["seconds"], bool(r.get("replayed"))))
    return out


def keep(scores, records_at):
    """-> the line saying where the records went, or why they did not.
    `records_at(sha, dirty)` makes them."""
    sha, dirty = commit(scores)
    if sha is None:
        return "no commit here, so nothing is kept per commit"
    lines = [json.dumps(r) + "\n" for r in records_at(sha, dirty)]
    Path(scores).parent.mkdir(parents=True, exist_ok=True)
    with Path(scores).open("a", encoding="utf-8") as f:
        f.write("".join(lines))
    return ("kept per commit: " + str(scores)
            + (", made with uncommitted changes, which compare does not count"
               if dirty else ""))


def readable(r):
    return (isinstance(r, dict) and set(FIELDS) <= set(r)
            and isinstance(r["sha"], str) and r["sha"]
            and r["outcome"] in OUTCOMES)


def read(path):
    """-> (records, problems). a line that is not a whole record is a
    problem, never a record."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], ["no scores kept at " + str(path)]
    except (OSError, UnicodeDecodeError) as e:
        return [], [str(path) + " cannot be read: " + str(e)]
    records, problems = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        if readable(r):
            records.append(r)
        else:
            problems.append("line " + str(n) + " of " + str(path)
                            + " is not a whole record")
    return records, problems


def named(records, sha):
    """-> the one recorded sha `sha` starts, or a ValueError saying why
    there is none."""
    found = sorted({r["sha"] for r in records if r["sha"].startswith(sha)})
    if len(found) > 1:
        raise ValueError(sha + " names more than one commit: "
                         + ", ".join(f[:12] for f in found))
    if not found:
        raise ValueError(sha[:7] + ": no record")
    return found[0]


def previous(records, head):
    """-> the nearest commit before `head` with records of its own. when git
    does not know `head`, the last other commit recorded before it."""
    kept = {r["sha"] for r in records if not r["dirty"]}
    known = ancestors(head)
    if known:
        return next((a for a in known[1:] if a in kept), None)
    shas = [r["sha"] for r in records if not r["dirty"]]
    before = shas[:shas.index(head)] if head in shas else shas
    return next((s for s in reversed(before) if s != head), None)


def by_task(records, sha):
    out = {}
    for r in records:
        if r["sha"] == sha and not r["dirty"]:
            out.setdefault((r["source"], r["flow"], r["task"]), []).append(r)
    return out


def passes(rs):
    return len([r for r in rs if r["outcome"] == PASS])


def shown(rs):
    """a single run is its outcome word: one run has no rate."""
    if len(rs) == 1:
        return rs[0]["outcome"]
    return str(passes(rs)) + "/" + str(len(rs))


def noisy(was, now):
    """whether the move is no larger than twice its standard error, the pass
    rate pooled over both sides' repeats."""
    nb, nh = len(was), len(now)
    rb, rh = passes(was) / float(nb), passes(now) / float(nh)
    p = (passes(was) + passes(now)) / float(nb + nh)
    return abs(rb - rh) <= 2 * math.sqrt(p * (1 - p) * (1.0 / nb + 1.0 / nh))


def ks(groups):
    counts = sorted({len(rs) for rs in groups})
    if not counts:
        return "0"
    return str(counts[0]) if len(counts) == 1 else (
        str(counts[0]) + " to " + str(counts[-1]))


def label(was, now):
    """-> (worse/better/same, what to read it with)."""
    rb, rh = passes(was) / float(len(was)), passes(now) / float(len(now))
    move = "same" if rb == rh else ("worse" if rh < rb else "better")
    replayed = (all(r["replayed"] for r in was),
                all(r["replayed"] for r in now))
    if all(replayed):
        return move, "replayed, no noise"
    note = {(True, False): "replayed on base, live on head",
            (False, True): "live on base, replayed on head"}.get(replayed)
    if move != "same" and noisy(was, now):
        k = ks([was, now])
        note = (note + ", " if note else "") + "inside the noise of k " + k
    return move, note


def head_line(side, sha, tasks, records):
    left = len([r for r in records if r["sha"] == sha and r["dirty"]])
    out = ["  " + side + " " + sha[:7] + "  N " + str(len(tasks))
           + " tasks, k " + ks(tasks.values())]
    if left:
        out.append("    " + str(left) + " record" + ("s" if left > 1 else "")
                   + " made with uncommitted changes, not counted")
    return out


def compare(records, base, head, flow=None):
    """-> (lines, failed). failed when a task that passed on the base fails
    every repeat of the head or has no record there, or either side has
    no record at all."""
    if flow:
        records = [r for r in records if r["flow"] == flow]
    was, now = by_task(records, base), by_task(records, head)
    out = ["# compare " + head[:7] + " against " + base[:7], ""]
    out += head_line("base", base, was, records)
    out += head_line("head", head, now, records)
    out.append("")
    if not was or not now:
        side = "base " + base[:7] if not was else "head " + head[:7]
        return out + ["  " + side + ": no record counted"], True
    out.append("  a/b is passes over repeats; a single repeat is its outcome")
    out.append("")
    failing, missing = [], []
    width = max(len(" ".join(k)) for k in set(was) | set(now))
    for key in sorted(set(was) | set(now)):
        name = " ".join(key).ljust(width)
        if key not in now:
            out.append("  " + name + "  " + shown(was[key])
                       + " on base, no record on head, so not a pass")
            if passes(was[key]):
                missing.append(" ".join(key))
            continue
        if key not in was:
            out.append("  " + name + "  new, no record on base, "
                       + shown(now[key]) + " on head")
            continue
        move, note = label(was[key], now[key])
        out.append("  " + name + "  " + move.ljust(6) + " "
                   + shown(was[key]) + " -> " + shown(now[key])
                   + (", " + note if note else ""))
        if passes(was[key]) and not passes(now[key]):
            failing.append(" ".join(key))
    if failing:
        out += ["", "  passed on base and fails on every repeat of head: "
                + ", ".join(failing)]
    if missing:
        out += ["", "  passed on base and has no record on head: "
                + ", ".join(missing)]
    return out, bool(failing or missing)
