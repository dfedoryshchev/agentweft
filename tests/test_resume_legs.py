"""a run resumed more than once reads every earlier leg, not only the last.

each leg is a run folder of its own, linked to the one it picked up by
`resumes` in its manifest. the handoff of the third leg used to read the
second leg's folder only, so what the first leg did, and the red-first proof
its gate recorded, were gone from it.
"""
import json
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, handoff, manifest, prompts, stops, summary

NL = chr(10)
ROLES = {"worker.md": "worker", "patcher.md": "patcher",
         "reviewer.md": "reviewer"}
class FM(object):
    steps = []


def a_leg(runs, run, resumes, lines, origin=None):
    folder = runs / run
    m = manifest.Manifest.new(folder, run, "fix", "fix",
                              ["worker.md", "patcher.md", "reviewer.md"],
                              ("", {}), origin=origin, resumes=resumes)
    m.save()
    with open(folder / "steps.jsonl", "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + NL)
    return folder


def block(*did):
    out = handoff.empty(handoff.PRESENT)
    out["did"] = list(did)
    return out


RED = {"gate": "red-test", "ok": True, "detail": "red, exit 1"}


def three_legs(runs):
    a_leg(runs, "fix-1", None,
          [{"step": "worker.md", "seconds": 2, "handoff": block("wrote the fix"),
            "gates": [RED]}])
    a_leg(runs, "fix-2", "fix-1",
          [{"step": "patcher.md", "seconds": 1, "handoff": handoff.empty()}],
          origin="fix-1")
    return a_leg(runs, "fix-3", "fix-2",
                 [{"step": "patcher.md", "seconds": 1,
                   "handoff": handoff.empty()}], origin="fix-1")


def test_a_resume_of_a_resume_reads_the_first_legs_block_and_red_proof(
        tmp_path):
    third = three_legs(tmp_path)
    before = summary.passes_of(third, ROLES, FM)
    assert [(p["step"], p.get("leg")) for p in before] == \
        [("worker.md", 1), ("patcher.md", 2), ("patcher.md", 3)]
    lines = summary.build("fix-4", "fix", "the ask", [], {"git": False}, [],
                          "", before=before)
    text = NL.join(lines)
    assert "worker did:" + NL + "- wrote the fix" in text
    assert "red first: gate-proven on worker.md in leg 1 (red, exit 1)" in text
    assert "no step handed over a block" not in text
    assert "- handoff missing: patcher.md in leg 2" in lines
    assert "- handoff missing: patcher.md in leg 3" in lines


def test_a_single_leg_reads_as_it_did(tmp_path):
    first = a_leg(tmp_path, "fix-1", None,
                  [{"step": "worker.md", "seconds": 2,
                    "handoff": block("wrote the fix"), "gates": [RED]}])
    before = summary.passes_of(first, ROLES, FM)
    assert [p["step"] for p in before] == ["worker.md"]
    assert "leg" not in before[0]
    lines = summary.build("fix-2", "fix", "the ask", [], {"git": False}, [],
                          "", before=before)
    assert "- red first: gate-proven on worker.md (red, exit 1)" in lines


def test_a_missing_earlier_leg_is_said_not_crashed_on(tmp_path):
    third = three_legs(tmp_path)
    for f in (tmp_path / "fix-1").iterdir():
        f.unlink()
    (tmp_path / "fix-1").rmdir()
    before = summary.passes_of(third, ROLES, FM)
    assert [p["step"] for p in before][1:] == ["patcher.md", "patcher.md"]
    lines = summary.build("fix-4", "fix", "the ask", [], {"git": False}, [],
                          "", before=before)
    gone = [l for l in lines if "fix-1" in l]
    assert gone and "gone" in gone[0]
    assert "red first: not proven by a gate" in NL.join(lines)


def test_the_third_leg_of_a_real_run_hands_over_what_the_first_did(
        tmp_path, monkeypatch):
    d = tmp_path / "flows" / "legs"
    d.mkdir(parents=True)
    body = "name: legs" + NL + "steps:" + NL
    for role, extra in (("a", "pause: user"), ("b", "pause: user"), ("c", "")):
        body = body + "  - role: " + role + NL + "    prompt: " + role + ".md" \
            + NL + ("    " + extra + NL if extra else "")
        (d / (role + ".md")).write_text("you are " + role + NL,
                                        encoding="utf-8")
    (d / "flow.yaml").write_text(body, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])

    def fake_call(prompt, timeout=None, cap=3, step="?", provider=None):
        if step == "a.md":
            return NL.join(["done", "HANDOFF", "DID:", "- made the change",
                            "END HANDOFF", ""]), False
        return "done by " + step + NL, False

    monkeypatch.setattr(engine, "call", fake_call)

    def go(*argv):
        monkeypatch.setattr(sys, "argv", ["run.py", "legs", "--force"]
                            + list(argv))
        return engine.main()

    def made():
        return set(p for p in (tmp_path / "runs").iterdir() if p.is_dir())

    go()
    [first] = made()
    go("--resume", first.name)
    [second] = made() - {first}
    assert go("--resume", second.name) == stops.EXIT_OK
    [third] = made() - {first, second}
    note = (third / summary.FILE).read_text(encoding="utf-8")
    assert "a did:" + NL + "- made the change" in note
    assert "no step handed over a block" not in note
