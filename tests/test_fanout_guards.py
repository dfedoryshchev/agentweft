"""the fanned-out step goes through the same per-step machinery as any other.

it did not. the fanout had its own branch that produced the handoff and jumped
straight to the next step, so the budget check, the gates, the preflight, the
boundary note and the step's own output file all belonged to the steps either
side of it and to nothing else. repo-audit is the only flow that configures a
preflight and it configures it on the fanned-out step, so the blast-radius
guard had never run anywhere.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts

NL = chr(10)
PLAN = "a.py | look at a" + NL + "b.py | look at b" + NL
RANKING = "src/hooks.ts 0.94" + NL + "src/util.ts 0.11" + NL

HEAD = ("name: {name}" + NL
        + "steps:" + NL
        + "  - role: planner" + NL
        + "    prompt: planner.md" + NL
        + "  - role: worker" + NL
        + "    prompt: worker.md" + NL
        + "    fanout: true" + NL
        + "    workers: 2" + NL)
TAIL = ("  - role: merge" + NL
        + "    prompt: merge.md" + NL
        + "journal: false" + NL
        + "provider:" + NL
        + "  provider: fake" + NL)
CONTEXT = ("context:" + NL
           + "  command: [\"not-a-real-server\"]" + NL
           + "  tool: hotspots" + NL)


def a_flow(tmp_path, body, name):
    root = tmp_path / "flows"
    d = root / name
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    (d / "instructions.md").write_text("audit what you are given." + NL,
                                       encoding="utf-8")
    for role in ("planner", "worker", "merge"):
        (d / (role + ".md")).write_text("you are the " + role + "." + NL,
                                        encoding="utf-8")
    return root


def go(tmp_path, monkeypatch, body, answers, name):
    """run main() over a throwaway flow, and say which steps were asked."""
    root = a_flow(tmp_path, body, name)
    asked = []

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        asked.append(step)
        return answers.get(step, "nothing to report"), False

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(engine.context, "risk_map", lambda conf: (RANKING, ""))
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(root)])
    monkeypatch.setattr(sys, "argv",
                        ["run.py", name, "--force", "--flows", str(root)])
    monkeypatch.chdir(tmp_path)
    engine.main()
    return asked


def index(tmp_path):
    p = tmp_path / "runs" / "index.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def run_dir(tmp_path):
    return [p for p in (tmp_path / "runs").iterdir() if p.is_dir()][0]


HOT = "i will rewrite src/hooks.ts"


def test_preflight_refuses_on_a_fanned_out_step(tmp_path, monkeypatch):
    body = (HEAD.format(name="fan-hot")
            + "    preflight:" + NL
            + "      mode: refuse" + NL
            + "      threshold: 0.7" + NL
            + TAIL + CONTEXT)
    asked = go(tmp_path, monkeypatch, body,
               {"planner.md": PLAN, "worker.md": HOT}, "fan-hot")
    assert "REFUSED" in index(tmp_path)
    assert "merge.md" not in asked


def test_a_fanned_out_step_writes_its_output_like_any_other(tmp_path, monkeypatch):
    """resume reads runs/<id>/<step>.md, and the handoff file points at it."""
    body = (HEAD.format(name="fan-out-file")
            + "    preflight:" + NL
            + "      mode: refuse" + NL
            + TAIL + CONTEXT)
    go(tmp_path, monkeypatch, body,
       {"planner.md": PLAN, "worker.md": HOT}, "fan-out-file")
    written = run_dir(tmp_path) / "worker.md"
    assert written.exists()
    assert written.read_text(encoding="utf-8").count(HOT) == 2


def test_a_gate_on_a_fanned_out_step_stops_the_run(tmp_path, monkeypatch):
    body = (HEAD.format(name="fan-gate")
            + "    gates:" + NL
            + "      - gate: length" + NL
            + "        max_lines: 1" + NL
            + TAIL)
    asked = go(tmp_path, monkeypatch, body,
               {"planner.md": PLAN, "worker.md": "one line"}, "fan-gate")
    assert "GATE  fan-gate  length at worker.md" in index(tmp_path)
    assert "merge.md" not in asked


def test_the_budget_is_checked_after_a_fanned_out_step(tmp_path, monkeypatch):
    body = HEAD.format(name="fan-budget") + TAIL + "max_calls: 1" + NL
    asked = go(tmp_path, monkeypatch, body,
               {"planner.md": PLAN, "worker.md": "one line"}, "fan-budget")
    assert "OVER  fan-budget  call cap: 3 > 1" in index(tmp_path)
    assert "merge.md" not in asked
