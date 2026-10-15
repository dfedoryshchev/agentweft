"""a judge's file says which verdicts it may give, and the runner holds the
answer to that list.

a judge that finds the request is really a change to the spec had nowhere to
say so but prose under an ok or a redo, and prose is not read. a file that
lists `VERDICT: spec change request` gives it a value, and that value stops
the run for a ruling with the judge's reason. a value the file does not list
fails the step, whatever the runner would otherwise have done with it.
"""
import sys

sys.path.insert(0, ".")
from agentweft.runner import engine, prompts, summary

NL = chr(10)
ASKS = ("# reviewer" + NL + NL + "do it." + NL + NL
        + "when the request is really a change to the spec, answer instead:"
        + NL + NL + "    VERDICT: spec change request" + NL + NL
        + "with the reason on the next line." + NL)
PLAIN = "# reviewer" + NL + NL + "do it." + NL


def a_flow(tmp_path, monkeypatch, name, judge, review, says):
    """a worker that answers, a judging step named `judge` whose file is
    `says` and whose answer is `review`, then a merge that only runs if the
    judge let the work through."""
    flow = tmp_path / "flows" / name
    flow.mkdir(parents=True)
    body = ("name: " + name + NL
            + "steps:" + NL
            + "  - role: worker" + NL
            + "    provider:" + NL
            + "      provider: fake" + NL
            + '      reply: "- a.md | look at a\\n"' + NL
            + "  - role: " + judge + NL
            + "    provider:" + NL
            + "      provider: fake" + NL
            + "      reply: " + review + NL
            + "  - role: merge" + NL
            + "provider:" + NL
            + "  provider: fake" + NL)
    (flow / "flow.yaml").write_text(body, encoding="utf-8")
    (flow / "instructions.md").write_text("the " + name + " flow." + NL,
                                          encoding="utf-8")
    (flow / "worker.md").write_text("# worker" + NL + NL + "do it." + NL,
                                    encoding="utf-8")
    (flow / (judge + ".md")).write_text(says, encoding="utf-8")
    (flow / "merge.md").write_text("# merge" + NL + NL + "do it." + NL,
                                   encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", ["flows"])
    monkeypatch.setattr(sys, "argv", ["run.py", name, "--force",
                                      "--flows", "flows"])
    engine.main()
    run_dir = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    journal = (tmp_path / "runs" / "journal.md").read_text().strip().split(NL)
    return run_dir, journal[-1]


def test_a_spec_change_request_stops_the_run_for_a_ruling_with_its_reason(
        tmp_path, monkeypatch):
    run_dir, line = a_flow(
        tmp_path, monkeypatch, "spec-change", "reviewer",
        '"VERDICT: spec change request\\n\\nthe request drops the export the'
        ' spec keeps\\n"', ASKS)
    assert line.split("  ")[2] == "parked at reviewer.md"
    assert "the request drops the export the spec keeps" in line
    assert not (run_dir / "merge.md").exists()
    handoff = (run_dir / summary.FILE).read_text(encoding="utf-8")
    assert "the request drops the export the spec keeps" in handoff


def test_a_spec_change_request_the_file_does_not_list_fails_the_step(
        tmp_path, monkeypatch, capsys):
    run_dir, line = a_flow(
        tmp_path, monkeypatch, "unlisted-change", "reviewer",
        '"VERDICT: spec change request\\n\\nthe request drops the export\\n"',
        PLAIN)
    assert line.split("  ")[2] == "failed at reviewer.md"
    assert not (run_dir / "merge.md").exists()
    assert '"spec change request"' in capsys.readouterr().out


def test_a_verdict_the_file_does_not_list_fails_the_step(
        tmp_path, monkeypatch, capsys):
    """a checking step whose file only allows an ok. a redo is a word the
    runner knows, and it walked the work back to the worker until the cap
    parked it; the file never offered it."""
    says = ("# checker" + NL + NL + "check the work, then answer:" + NL + NL
            + "    VERDICT: ok" + NL)
    run_dir, line = a_flow(tmp_path, monkeypatch, "ok-only", "checker",
                           '"VERDICT: redo\\n\\nnot good\\n"', says)
    assert line.split("  ")[2] == "failed at checker.md"
    assert not (run_dir / "merge.md").exists()
    assert '"redo"' in capsys.readouterr().out


def test_a_listed_ok_still_lets_the_work_through(tmp_path, monkeypatch):
    run_dir, line = a_flow(tmp_path, monkeypatch, "listed-ok", "reviewer",
                           '"VERDICT: ok\\n\\nfine\\n"', ASKS)
    assert line.split("  ")[2] == "ok"
    assert (run_dir / "merge.md").exists()
