"""a run splits its budget into a block per step before its first call, says
RISKY up front when the blocks do not fit the cap, and keeps a buffer that
takes what a step leaves and pays what a step runs over."""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts, stops

NL = chr(10)
THREE = [("a", []), ("b", []), ("c", [])]
SHARED = [("planner", []), ("worker", []), ("tester", [])]


def a_flow(tmp_path, monkeypatch, name, steps, tail=""):
    d = tmp_path / "flows" / name
    d.mkdir(parents=True)
    body = "name: " + name + NL + "steps:" + NL
    for role, extra in steps:
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" + NL
        for line in extra:
            body = body + "    " + line + NL
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body + tail, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    return d


def asking(monkeypatch, answer=None, first=None):
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if not asked and first is not None:
            first()
        asked.append(step)
        if answer is not None:
            return answer(step, prompt), False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)
    return asked


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run.py"] + list(argv))
    return engine.main()


def folders(tmp_path):
    runs = tmp_path / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() \
        else []


def lines(folder):
    return [json.loads(l) for l in (folder / "steps.jsonl")
            .read_text(encoding="utf-8").split(NL) if l.strip()]


def blocks(folder):
    """-> {step: estimate} from the plan file's table, plus its buffer."""
    out = {}
    assert (folder / "budget-plan.md").is_file()
    for line in (folder / "budget-plan.md").read_text(
            encoding="utf-8").split(NL):
        parts = line.split()
        if len(parts) >= 2 and parts[-1].isdigit() and (
                parts[0].endswith(".md") or parts[0] == "buffer"):
            out[parts[0]] = int(parts[-1])
    return out


def test_a_flow_whose_estimate_is_over_its_cap_says_risky_before_any_call(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "tight", THREE, tail="max_calls: 2" + NL)
    before = []
    asking(monkeypatch, first=lambda: before.append(capsys.readouterr().out))
    assert run(monkeypatch, "tight", "--force") == stops.EXIT_STOP
    [said] = before
    assert "RISKY" in said
    assert "3 calls" in said and "2" in said
    [first] = folders(tmp_path)
    assert "RISKY" in (first / "budget-plan.md").read_text(encoding="utf-8")


def test_a_flow_that_fits_is_not_called_risky(tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "roomy", THREE, tail="max_calls: 9" + NL)
    asking(monkeypatch)
    assert run(monkeypatch, "roomy", "--force") == stops.EXIT_OK
    assert "RISKY" not in capsys.readouterr().out


def test_the_plan_file_has_one_block_per_step_split_by_measured_shares(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "split", SHARED,
           tail="max_tokens: 100000" + NL)
    seen = []
    asking(monkeypatch, first=lambda: seen.extend(folders(tmp_path)))
    assert run(monkeypatch, "split", "--force") == stops.EXIT_OK
    [first] = seen
    got = blocks(first)
    assert set(got) == {"planner.md", "worker.md", "tester.md", "buffer"}
    assert got["worker.md"] > got["tester.md"] > got["planner.md"]
    assert sum(got.values()) == 100000
    text = (first / "budget-plan.md").read_text(encoding="utf-8")
    assert "shares" in text and "RISKY" not in text


def test_estimates_come_from_earlier_runs_of_the_same_flow_here(
        tmp_path, monkeypatch, capsys):
    a_flow(tmp_path, monkeypatch, "again", SHARED,
           tail="max_tokens: 100000" + NL)
    asking(monkeypatch)
    assert run(monkeypatch, "again", "--force") == stops.EXIT_OK
    [earlier] = folders(tmp_path)
    counted = {"planner.md": 20000, "worker.md": 90000, "tester.md": 5000}
    kept = []
    for line in lines(earlier):
        line["tokens"] = {"counted": True, "input": counted[line["step"]],
                          "output": 0, "cache_read": 0, "cache_creation": 0}
        kept.append(json.dumps(line))
    (earlier / "steps.jsonl").write_text(NL.join(kept) + NL, encoding="utf-8")
    capsys.readouterr()
    before = []
    asking(monkeypatch, first=lambda: before.append(capsys.readouterr().out))
    run(monkeypatch, "again", "--force")
    [said] = before
    assert "RISKY" in said and "115000" in said
    [later] = [p for p in folders(tmp_path) if p != earlier]
    got = blocks(later)
    assert got["worker.md"] == 90000 and got["planner.md"] == 20000
    assert "earlier run" in (later / "budget-plan.md").read_text(
        encoding="utf-8")


def test_a_step_that_overruns_draws_from_the_buffer_and_says_so(
        tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, "over", THREE,
           tail="max_tokens: 100000" + NL)

    def answer(step, prompt):
        return ("x" * 140000 if step == "c.md" else "small") + NL

    asking(monkeypatch, answer)
    assert run(monkeypatch, "over", "--force") == stops.EXIT_OK
    [first] = folders(tmp_path)
    planned = blocks(first)
    a, b, c = lines(first)
    assert a["budget"]["planned"] == planned["a.md"]
    assert a["budget"]["spent"] < a["budget"]["planned"]
    assert "left to the buffer" in a["budget"]["risk"]
    assert a["budget"]["buffer"] > planned["buffer"]
    health = c["budget"]
    assert health["planned"] == planned["c.md"]
    assert health["spent"] > health["planned"]
    assert "drawn from the buffer" in health["risk"]
    assert health["buffer"] == b["budget"]["buffer"] - (health["spent"]
                                                        - health["planned"])


GOLDEN = __import__("pathlib").Path(__file__).resolve().parent / "golden"


def test_the_step_that_asked_the_lead_is_charged_its_own_call():
    steps = json.loads((GOLDEN / "build-feature" / "lead-decides.json")
                       .read_text(encoding="utf-8"))["steps"]
    asked = [s for s in steps if s["outcome"] == "asked"][0]
    assert asked["tokens"]["counted"] and asked["cost"]
    assert asked["budget"]["spent"] == 1, asked["budget"]
    lead = [i for i, s in enumerate(steps) if s["outcome"] == "decided"][0]
    before = [s for s in steps[:lead] if s["step"] == steps[lead]["step"]]
    assert steps[lead]["budget"]["spent"] == \
        before[-1]["budget"]["spent"] + 1, steps[lead]["budget"]


def test_a_line_closed_after_one_opened_inside_it_keeps_its_own_calls(
        tmp_path):
    from agentweft.guardrails import blocks
    from agentweft.runner import trace

    class Spent(object):
        max_tokens = None
        max_calls = 10
        capped = 0
        calls = 0

    class P(object):
        name = "fake"
        command = "fake"
        choice = None

        def asks_for(self):
            return "m"

        def granted(self):
            return None

    budget = Spent()
    plan = blocks.Plan(budget, ["worker.md", "lead.md"], {})
    t = trace.Trail(tmp_path, plan=plan)
    budget.calls = 2
    asker = t.open("worker.md", [], P(), None, output="asks")
    budget.calls = 3
    lead = t.open("lead.md", [], P(), "worker.md", output="decides")
    t.close(lead, "decided", to="worker.md")
    t.close(asker, "asked", to="lead.md")
    said = dict((json.loads(x)["step"], json.loads(x)["budget"]["spent"])
                for x in (tmp_path / "steps.jsonl").read_text(
                    encoding="utf-8").splitlines())
    assert said == {"worker.md": 2, "lead.md": 1}
