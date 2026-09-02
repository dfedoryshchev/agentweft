import pathlib
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.roles import resolver
from agentweft.runner import prompts


def flow_prompts(root="flows"):
    """every prompt file in every flow, template included."""
    for folder in sorted(pathlib.Path(root).iterdir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            yield path


def test_the_library_keeps_the_roles_that_repeat():
    assert resolver.library_roles() == ["merge", "planner", "reviewer", "verify"]


def test_no_flow_repeats_a_line_the_library_already_says():
    """the whole reason for a library: the role's contract is written once.

    verbatim lines only. it cannot see two flows saying the same thing in
    different words, which is most of what a library is for, but it catches
    the class that actually grew - the verdict block, which had been pasted
    into five reviewers and forgotten in the sixth.
    """
    repeats = []
    for path in flow_prompts():
        shared = [l.strip() for l in resolver.role_prompt(path.name).split("\n")
                  if l.strip()]
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip() and line.strip() in shared:
                repeats.append(str(path) + ": " + line.strip())
    assert repeats == []


def test_a_role_the_library_has_no_words_for_is_the_flows_own():
    assert resolver.role_prompt("worker.md") == ""
    text = prompts.read("weekly-digest", "worker.md")
    assert text == prompts.flow_path("weekly-digest", "worker.md").read_text()


def test_the_flow_goes_first_and_the_library_after():
    text = prompts.read("repo-audit", "reviewer.md")
    own = prompts.flow_path("repo-audit", "reviewer.md").read_text()
    assert text.startswith(own.rstrip("\n"))
    assert text.endswith(resolver.role_prompt("reviewer.md"))


def test_a_role_with_no_file_in_the_flow_comes_from_the_library():
    """the template stopped shipping three prompts that were never its own.

    what was in them is what the library says, so copying the template gets
    them without the copy: `flows/_template` is a flow.yaml, the rules for the
    flow, and the one role the library cannot write for you.
    """
    for name in ("planner.md", "reviewer.md", "verify.md"):
        assert not prompts.flow_path("_template", name).exists(), name
        assert prompts.read("_template", name) == resolver.role_prompt(name)
    assert prompts.flow_path("_template", "worker.md").exists()


def test_a_role_nobody_has_words_for_anywhere_is_still_an_error():
    with pytest.raises(FileNotFoundError):
        prompts.read("weekly-digest", "nobody.md")


def test_every_reviewer_still_gets_the_verdict_contract():
    """the block moved out of five files; it has to reach the model from all
    six, including the one that never had it."""
    for name in sorted(p.name for p in pathlib.Path("flows").iterdir()
                       if p.is_dir() and not p.name.startswith("_")):
        spec = runner.config(name)
        for step in spec.steps:
            if step["role"] != "reviewer":
                continue
            text = prompts.read(name, step.get("prompt", step["role"] + ".md"))
            assert "VERDICT: ok" in text, name
            assert "VERDICT: redo" in text, name
