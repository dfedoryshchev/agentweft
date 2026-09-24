import pathlib
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import runner
from agentweft.flow import reader, spec
from agentweft.roles import resolver
from agentweft.runner import prompts

NL = chr(10)
VERDICT = [l.strip() for l in resolver.role_prompt("reviewer.md").split(NL)
           if l.strip()][0]

PERSONAS = ("name: personas" + NL
            + "steps:" + NL
            + "  - role: worker" + NL
            + "    prompt: worker.md" + NL
            + "  - role: reviewer" + NL
            + "    prompt: reviewer-minimalist.md" + NL
            + "  - role: reviewer" + NL
            + "    prompt: reviewer-maximalist.md" + NL)


def declared_roles(folder):
    """-> prompt file -> the role the flow's own steps say it is."""
    fm = spec.load(reader.read((folder / "flow.yaml").read_text(encoding="utf-8")))
    return {spec.step_id(step): step["role"] for step in fm.steps}


def library_repeats(root="flows"):
    """-> "<file>: <line>", once per prompt line its role already gets anyway.

    the lookup goes through flow.yaml because the file name is not the role:
    a role can be two files, and neither of them has to be called after it.
    """
    found = []
    for folder in sorted(pathlib.Path(root).iterdir()):
        if not (folder / "flow.yaml").is_file():
            continue
        roles = declared_roles(folder)
        for path in sorted(folder.glob("*.md")):
            role = roles.get(path.name)
            if role is None:
                continue
            shared = [l.strip()
                      for l in resolver.role_prompt(role + ".md").split(NL)
                      if l.strip()]
            for line in path.read_text(encoding="utf-8").split(NL):
                if line.strip() and line.strip() in shared:
                    found.append(str(path) + ": " + line.strip())
    return found


def a_flow(tmp_path, minimalist, maximalist):
    root = tmp_path / "flows"
    folder = root / "personas"
    folder.mkdir(parents=True)
    (folder / "flow.yaml").write_text(PERSONAS, encoding="utf-8")
    (folder / "instructions.md").write_text("review what you are given." + NL,
                                            encoding="utf-8")
    (folder / "worker.md").write_text("do the work." + NL, encoding="utf-8")
    (folder / "reviewer-minimalist.md").write_text(minimalist, encoding="utf-8")
    (folder / "reviewer-maximalist.md").write_text(maximalist, encoding="utf-8")
    return root


def test_the_library_keeps_the_roles_that_repeat():
    assert resolver.library_roles() == ["judge", "merge", "planner", "reviewer",
                                        "verify"]


def test_no_flow_repeats_a_line_the_library_already_says():
    """the whole reason for a library: the role's contract is written once.

    verbatim lines only. it cannot see two flows saying the same thing in
    different words, which is most of what a library is for, but it catches
    the class that actually grew - the verdict block, which had been pasted
    into five reviewers and forgotten in the sixth.
    """
    assert library_repeats() + library_repeats("examples") == []


def test_a_persona_file_is_checked_against_the_words_its_role_already_says(
        tmp_path):
    """a second file for one role is not named after the role, so looking the
    library up by the file name asks it about a name it has never heard of and
    gets back nothing to compare with."""
    assert resolver.role_prompt("reviewer-minimalist.md") == ""
    root = a_flow(tmp_path,
                  "# reviewer, minimalist" + NL + NL + VERDICT + NL,
                  "# reviewer, maximalist" + NL + NL + "say what is missing."
                  + NL)
    found = library_repeats(root)
    assert len(found) == 1, found
    assert "reviewer-minimalist.md" in found[0]
    assert found[0].endswith(": " + VERDICT)


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
