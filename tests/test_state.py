import json
import sys

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.runner import engine, prompts, resume, state, stops

LINE = "the last run was "


def test_two_flows_do_not_clobber_each_other(tmp_path, monkeypatch):
    # the old code read the whole dict, edited one key and wrote it all back,
    # so this second save used to wipe the first
    state.save_state("ops-check", {"last_run": "a.md"}, tmp_path)
    state.save_state("weekly-digest", {"last_run": "b.md"}, tmp_path)

    assert state.load_state("ops-check", tmp_path)["last_run"] == "a.md"
    assert state.load_state("weekly-digest", tmp_path)["last_run"] == "b.md"


def test_unknown_flow_is_empty(tmp_path, monkeypatch):
    assert state.load_state("never-run", tmp_path) == {}


def test_a_place_inside_a_repo_is_kept_under_the_repo(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / "src").mkdir()
    state.save_state("f", {"last_run": "a.md"}, tmp_path / "repo" / "src")
    assert state.load_state("f", tmp_path / "repo")["last_run"] == "a.md"


def test_another_task_in_the_same_project_is_kept_apart(tmp_path):
    state.save_state("f", {"last_run": "a.md"}, tmp_path, task="one")
    assert state.load_state("f", tmp_path, task="one")["last_run"] == "a.md"
    assert state.load_state("f", tmp_path, task="two") == {}


# through the engine


def a_flow(tmp_path, monkeypatch, pause=False, tasked=False):
    d = tmp_path / "home" / "flows" / "kept"
    d.mkdir(parents=True)
    for step in ["planner.md", "worker.md"]:
        (d / step).write_text("# step\n\ndo the thing.\n", encoding="utf-8")
    (d / "instructions.md").write_text(
        "two steps." + (" {TASK}" if tasked else "") + "\n", encoding="utf-8")
    (d / "flow.yaml").write_text(
        "name: kept\n"
        "steps:\n"
        "  - role: planner\n"
        "    prompt: planner.md\n"
        + ("    pause: user\n" if pause else "")
        + "  - role: worker\n"
        "    prompt: worker.md\n"
        "provider:\n"
        "  provider: fake\n"
        '  reply: "VERDICT: ok\\n\\ndone\\n"\n',
        encoding="utf-8")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prompts, "FLOW_ROOT", [str(tmp_path / "home" / "flows")])
    monkeypatch.setattr(resume, "JOURNAL", None)


def planner_prompts(monkeypatch):
    sent = []
    real = engine.call
    monkeypatch.setattr(engine, "call", lambda prompt, step="?", **kw: (
        sent.append(prompt) if step == "planner.md" else None)
        or real(prompt, step=step, **kw))
    return sent


def go(monkeypatch, place, *more):
    monkeypatch.setattr(sys, "argv", ["run.py", "kept", "--force",
                                      "--workdir", str(place)] + list(more))
    return engine.main()


def kept_under_the_runs():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in state.RUNS.glob("*.json")]


def test_two_projects_from_one_install_do_not_see_each_other(tmp_path,
                                                            monkeypatch):
    a_flow(tmp_path, monkeypatch)
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a") == 0
    assert go(monkeypatch, tmp_path / "b") == 0
    assert [LINE in p for p in sent] == [False, False]


def test_the_same_project_sees_its_own_last_run(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a") == 0
    assert go(monkeypatch, tmp_path / "a") == 0
    assert [LINE in p for p in sent] == [False, True]


def test_a_stopped_run_writes_its_state_under_the_runs_root(tmp_path,
                                                           monkeypatch):
    a_flow(tmp_path, monkeypatch, pause=True)
    assert go(monkeypatch, tmp_path / "a") != 0
    [folder] = [p.name for p in state.RUNS.iterdir() if p.is_dir()]
    found = kept_under_the_runs()
    assert len(found) == 1
    kept = found[0]
    lines = (state.RUNS / "journal.md").read_text(encoding="utf-8").split("\n")
    [end] = [stops.read(l) for l in lines
             if l.strip() and stops.read(l).kind != "running"]
    assert (kept["run"], kept["ended"]) == (folder, end.status)
    assert end.status.endswith(" at planner.md")
    assert kept["workdir"] == str((tmp_path / "a").resolve())


def test_the_old_file_of_another_project_is_ignored(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch)
    state.STATE_DIR.mkdir(parents=True)
    (state.STATE_DIR / "kept.json").write_text(json.dumps(
        {"last_run": "kept-other.md", "workdir": str(tmp_path / "b")}),
        encoding="utf-8")
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a") == 0
    assert [LINE in p for p in sent] == [False]


def test_the_old_file_names_no_task_so_it_gives_no_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, tasked=True)
    state.RUNS.mkdir(parents=True, exist_ok=True)
    (state.RUNS / "kept-before.md").write_text("before\n", encoding="utf-8")
    state.STATE_DIR.mkdir(parents=True)
    (state.STATE_DIR / "kept.json").write_text(json.dumps(
        {"last_run": "kept-before.md",
         "workdir": str((tmp_path / "a").resolve())}), encoding="utf-8")
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert LINE not in sent[0]
    assert "kept-before.md" not in sent[1] and LINE in sent[1]


def saved_output():
    [kept] = kept_under_the_runs()
    return (state.RUNS / kept["last_run"]).resolve()


def test_another_task_in_the_same_repo_gets_no_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, tasked=True)
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert go(monkeypatch, tmp_path / "a", "--task", "two") == 0
    assert [LINE in p for p in sent] == [False, False]


def test_the_same_task_is_told_where_its_last_output_is(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, tasked=True)
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    out = saved_output()
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert out.is_absolute() and out.is_file()
    assert LINE + str(out) + "." in sent[1]


def test_a_last_output_that_was_deleted_gives_no_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, tasked=True)
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    saved_output().unlink()
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert LINE not in sent[1]


def test_a_kept_run_of_another_place_gives_no_line(tmp_path, monkeypatch):
    a_flow(tmp_path, monkeypatch, tasked=True)
    state.RUNS.mkdir(parents=True, exist_ok=True)
    (state.RUNS / "kept-other.md").write_text("other\n", encoding="utf-8")
    state.save_state("kept", {"last_run": "kept-other.md",
                              "workdir": str((tmp_path / "b").resolve())},
                     tmp_path / "a", "one")
    sent = planner_prompts(monkeypatch)
    assert go(monkeypatch, tmp_path / "a", "--task", "one") == 0
    assert LINE not in sent[0]
