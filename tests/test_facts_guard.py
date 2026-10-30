"""only the runner writes the project's facts.

a step's Write and Edit tools are refused under facts/, a step that changes
the store anyway fails like a gate and the store is put back, and a fact the
runner is asked to write is held to the record first: its scope is in the
place, its evidence is there, its anchor is hashed by the runner, it carries
no secret, and a run writes at most a few new ones."""
import json
import sys

import pytest

sys.path.insert(0, ".")
from agentweft import providers
from agentweft.guardrails import shellwrite
from agentweft.orchestrate import facts
from agentweft.runner import stops

try:
    from agentweft.guardrails import factsguard
except ImportError:
    factsguard = None

import test_spec_files as sf

NL = chr(10)
CODE = NL.join(["import os", "", "def parse(line):", "    if not line:",
                "        raise ValueError('empty')", "    return line.split()",
                ""])


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def entry(id, scope, claim):
    return ("## " + id + " live" + NL + "scope: " + scope + NL
            + "kind: convention" + NL + "claim: " + claim + NL
            + "why: the spec says so" + NL)


def proposal(**given):
    fields = {"scope": ["pkg/a.py"], "kind": "why", "label": "none",
              "claim": "parse raises on an empty line, never returns []",
              "why": "the caller counts on the raise for its one error line",
              "source": 'seq 2 worker.md; evidence: pkg/a.py:5 "raise'
                        ' ValueError"',
              "anchor": "pkg/a.py:3-6"}
    fields.update(given)
    return factsguard.Proposal(fields)


def a_store(tmp_path, cap=3, ran=(), stamps=()):
    put(tmp_path, "pkg/a.py", CODE)
    store = factsguard.Store(tmp_path, cap=cap)
    return store, factsguard.Record(tmp_path, ran=ran, stamps=stamps)


def test_a_step_that_edits_a_fact_fails_like_a_gate_and_it_is_put_back(
        tmp_path, monkeypatch):
    place = sf.a_place(tmp_path / "repo")
    before = entry("F-0001", "report.py", "report keeps the given order")
    put(place, "facts/report.py.md", before)
    sf.git(place, "add", ".")
    sf.git(place, "commit", "-qm", "facts")
    sf.flow_with(tmp_path, "additions")
    does = sf.worker_writes(sf.SPEC)
    writes, said = does["worker.md"]
    does["worker.md"] = (dict(writes, **{"facts/report.py.md": before.replace(
        "keeps the given order", "may sort")}), said)
    code, called = sf.running(tmp_path, monkeypatch, place, does, False)
    assert code == stops.exit_code(stops.GATE)
    assert called == ["tester.md", "worker.md", "worker.md"]
    gates = sf.read(sf.folders()[-1] / "gates.md")
    assert "facts/report.py.md was changed by worker.md" in gates
    assert "facts come only from the runner" in gates
    assert (place / "facts" / "report.py.md").read_text(
        encoding="utf-8") == before


def test_a_step_that_adds_a_facts_file_fails_and_it_is_taken_away(tmp_path):
    store = factsguard.Store(tmp_path)
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0001", "pkg/", "made up"))
    said = store.check("worker.md")
    assert "facts/pkg/_folder.md was changed by worker.md" in said
    assert "added or edited F-0001" in said
    assert not (tmp_path / "facts" / "pkg" / "_folder.md").exists()
    assert store.check("worker.md") == ""


def test_a_projects_own_files_in_a_facts_folder_stay_the_projects(tmp_path):
    from agentweft.guardrails import snapshot

    put(tmp_path, "facts/capitals.json", '{"fr": "Paris"}')
    put(tmp_path, "facts/F-0001.md", entry("F-0001", ".", "by hand"))
    store = factsguard.Store(tmp_path)
    start = snapshot.take(tmp_path)
    put(tmp_path, "facts/capitals.json", '{"fr": "Paris", "de": "Berlin"}')
    put(tmp_path, "facts/towns/uk.csv", "london" + NL)
    assert store.check("worker.md") == ""
    assert (tmp_path / "facts" / "towns" / "uk.csv").is_file()
    assert "Berlin" in (tmp_path / "facts" / "capitals.json").read_text(
        encoding="utf-8")
    assert start.product_changed() == ["facts/capitals.json",
                                       "facts/towns/uk.csv"]
    put(tmp_path, "facts/F-0001.md", entry("F-0001", ".", "edited"))
    assert "facts/F-0001.md was changed by worker.md" in store.check(
        "worker.md")
    keep = str(tmp_path / "facts") + "/"
    data = {"tool_name": "Write", "cwd": str(tmp_path), "session_id": "s",
            "tool_input": {"file_path": str(tmp_path / "facts" / "a.json"),
                           "content": "x"}}
    assert shellwrite.decide([str(tmp_path / "d.jsonl"), "--keep", keep],
                             json.dumps(data)) == (0, "")


def test_a_proposal_with_a_token_shaped_string_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    fact, why = store.add(proposal(claim="the deploy reads " + token),
                          record)
    assert fact is None
    assert why == "it looks like a secret: a token in claim"
    assert token not in why
    assert facts.read(tmp_path) == []


def test_a_proposal_naming_a_credential_file_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(why="the keys are in .env, read at"
                                       " start"), record)
    assert fact is None
    assert why == "it looks like a secret: a credential file in why"


# built from parts: the repo's own leak gate refuses a machine path written
# out whole, and these are the shapes the store must refuse
DRIVE_D, DRIVE_C, HOME, TMP = "D" + ":", "C" + ":", "/" + "home", "/" + "tmp"


@pytest.mark.parametrize("key, said, path", [
    ("claim", "parse reads " + DRIVE_D + "/work/place/pkg/a.py line by line",
     DRIVE_D + "/work"),
    ("why", "the run's copy at " + DRIVE_C + "\\" + "Users\\me\\pkg broke it",
     DRIVE_C + "\\" + "Users"),
    ("why", "the cache under " + HOME + "/me/.cache/pkg went stale",
     HOME + "/me"),
    ("claim", "the config at ~/pkg/settings.toml is read first", "~/pkg"),
    ("why", "the share \\\\build01\\drops\\pkg held the old copy",
     "\\\\build01"),
    ("source", 'seq 2 worker.md; evidence: pkg/a.py:5 "raise ValueError"'
     " in " + TMP + "/run/pkg/a.py", TMP + "/run")])
def test_a_fact_field_that_holds_an_absolute_path_is_refused(
        tmp_path, key, said, path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(**{key: said}), record)
    assert fact is None
    assert why.startswith("it names a path on the machine it ran on ("
                          + path), why
    assert why.endswith(" in " + key)
    assert facts.read(tmp_path) == []


@pytest.mark.parametrize("claim", [
    "parse reads the request path /index.html as given",
    "see https://example.com/docs/a for the format",
    "TASK.md:3 / TASK.md:9 both say it",
    'a line split on "\\\\r\\\\n" keeps its last field',
    "a path like pkg/a.py:5 is relative"])
def test_a_url_a_request_path_or_a_relative_one_is_no_machine_path(
        tmp_path, claim):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(claim=claim), record)
    assert why == "" and fact is not None


@pytest.mark.parametrize("path", [
    "/c/" + "Users/me/pkg/a.py",
    "/d/" + "work/place/pkg/a.py",
    "\\" + "\\" + "10.0.0.5\\drops\\pkg\\a.py",
    "/" + "/build01/drops/pkg/a.py"])
def test_a_machine_path_as_another_shell_prints_it_is_found(path):
    assert factsguard.machine_path("the file is " + path) == path


@pytest.mark.parametrize("text", [
    "https://example.com/tmp/x", "see http://example.com/c/docs/x",
    '"\\r\\n"', '"\\\\r\\\\n"', "/index.html", "a.py:12", "a/b/c/d.py",
    "x = a //2"])
def test_a_url_a_quote_or_a_relative_path_is_found_no_machine_path(text):
    assert factsguard.machine_path(text) == ""


def test_a_proposal_line_that_holds_an_absolute_path_is_never_kept(tmp_path):
    store, _ = a_store(tmp_path)
    assert store.propose(["## edit README.md (r)",
                          "after: run " + DRIVE_D + "/work/tool.exe"]
                         ).startswith(
        "it names a path on the machine it ran on")
    assert not (tmp_path / "facts" / "PROPOSED.md").exists()


MACHINE = ("the machine's state as the run went, not the project's: a later"
           " run on a sound machine would be handed it")


def test_a_gate_issue_naming_an_os_error_code_is_the_machines_and_refused(
        tmp_path):
    store, record = a_store(tmp_path)
    for said in ("the tests that run the cli fail with OSError: [WinError 87]"
                 " The parameter is incorrect",
                 "subprocess raises [Errno 22] Invalid argument at spawn"):
        fact, why = store.add(proposal(kind="gate-issue", scope=["pkg/"],
                                       claim=said), record)
        assert fact is None
        assert why == "a gate-issue that names an OS error code is " + MACHINE
    assert facts.read(tmp_path) == []


HOSTED = ("is how this host behaved, not the project's way: a later run on"
          " another machine would be handed it as a rule of the project")


def test_a_convention_about_the_runs_own_shell_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        kind="convention",
        claim="line-break and non-ASCII characters in tests are written as"
              " Python escapes such as \\N{LINE SEPARATOR}, never as raw"
              " bytes, and the file is written with the Write tool, not a"
              " shell",
        why="in this Windows Git Bash, sed, heredocs and python -c lost"
            " backslash escapes and non-ASCII characters on the way to"
            " files; patcher had to revert reader.py with git checkout"),
        record)
    assert fact is None
    assert why == ("a convention that names the run's own machine or shell"
                   " (this Windows) " + HOSTED)
    assert facts.read(tmp_path) == []


def test_a_gate_issue_about_the_runs_own_host_is_refused(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    for claim in ("Under the red-first and full-suite gates, tests that start"
                  " the CLI through `run_cli` fail with OSError WinError 87."
                  " The same tests pass when run by hand in the step shell.",
                  "the gate's pytest cannot start the CLI on this machine;"
                  " by hand it starts"):
        fact, why = store.add(proposal(kind="gate-issue", scope=["pkg/"],
                                       claim=claim), record)
        assert fact is None, claim
    assert why == ("a gate-issue that names the run's own machine or shell"
                   " (this machine) " + HOSTED)


def test_a_convention_that_names_an_os_for_the_product_is_written(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    for n, (claim, why) in enumerate((
            ("paths are written with forward slashes on Windows and Linux",
             "the CLI supports Windows, macOS and Linux alike"),
            ("parse runs its subprocess with shell=False",
             "a line of input must never reach a shell"),
            ("rounding boundary tests use decimal boundaries, not whole"
             " numbers", "at whole-number boundaries half-even also rounds"
             " up, so those tests passed without the fix"),
            ("the release scripts are PowerShell modules, one per target",
             "the release job on the build agents loads them by name"),
            ("the windows build links with MinGW, not MSVC",
             "the C extension is built the same way on every agent"),
            ("install.sh writes its config with a heredoc",
             "the installer has to run where only sh is"))):
        fact, said = store.add(proposal(kind="convention", claim=claim,
                                        why=why), record)
        assert said == "" and fact is not None, claim


def test_a_convention_that_names_a_shell_tool_with_the_run_s_host_is_refused(
        tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        kind="convention", claim="files are written with the Write tool",
        why="PowerShell on the step's machine mangled the quotes"), record)
    assert fact is None
    assert "(the step's machine)" in why


def test_a_gate_issue_of_the_project_is_held_like_any_fact(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(kind="gate-issue", scope=["pkg/"],
                                   claim="red-first cannot replay pkg/: the"
                                         " tests import a module built at"
                                         " install"), record)
    assert MACHINE not in why
    fact, why = store.add(proposal(claim="parse raises OSError [Errno 22] on"
                                         " a bad path"), record)
    assert MACHINE not in why


def test_a_long_mixed_string_is_refused_and_a_hash_is_not(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        claim="the key is Zq8vT2mX9pL4rW7nB3kY6hJ1sD5fG0aQ"), record)
    assert why == "it looks like a secret: a long random string in claim"
    fact, why = store.add(proposal(claim="the start was c5aa5960d460d126ed02"
                                         "e3169f463c2fac0b9d11d90833e83fef42f4"
                                         "a698b733"), record)
    assert why == "" and fact is not None


def test_a_proposal_whose_quote_is_not_at_that_line_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(
        source='seq 2 worker.md; evidence: pkg/a.py:2 "raise ValueError"'),
        record)
    assert fact is None
    assert why == ('the evidence does not hold: "raise ValueError" is not at'
                   " pkg/a.py:2")


def test_evidence_over_a_wrapped_line_holds_only_with_the_lines_cited(
        tmp_path):
    store, record = a_store(tmp_path, cap=9)
    put(tmp_path, "pkg/README.md", NL.join([
        "an empty line is an error: parse raises", "ValueError and never",
        "returns an empty list.", ""]))
    quote = "parse raises ValueError and never returns an empty list"
    fact, why = store.add(proposal(
        source='seq 2 worker.md; evidence: pkg/README.md:1 "' + quote + '"'),
        record)
    assert fact is None
    assert why == ('the evidence does not hold: "' + quote + '" is not at'
                   " pkg/README.md:1")
    fact, why = store.add(proposal(
        source='seq 2 worker.md; evidence: pkg/README.md:1-3 "' + quote
               + '"'), record)
    assert why == "" and fact is not None


CLI = NL.join(["def check(args):", "    if args.curve < 0:",
               '        raise GradebookError(f"invalid --curve: {args.curve}")',
               "", "def key_of(entry):",
               '    return f"{entry.status // 100}xx"', ""])


def quoting(line, quote):
    return 'seq 2 worker.md; evidence: pkg/cli.py:' + line + ' "' + quote + '"'


def test_evidence_with_its_inner_quotes_escaped_holds(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    put(tmp_path, "pkg/cli.py", CLI)
    for n, (line, quote) in enumerate((
            ("3", '        raise GradebookError(f\\"invalid --curve:'
                  ' {args.curve}\\")'),
            ("6", '    return f\\"{entry.status // 100}xx\\"'))):
        fact, why = store.add(proposal(claim="claim " + str(n),
                                       source=quoting(line, quote)), record)
        assert why == "" and fact is not None


def test_evidence_with_its_inner_quotes_as_they_are_holds(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    put(tmp_path, "pkg/cli.py", CLI)
    fact, why = store.add(proposal(source=quoting(
        "6", '    return f"{entry.status // 100}xx"')), record)
    assert why == "" and fact is not None


def test_escaped_evidence_that_is_not_in_the_file_is_refused(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    put(tmp_path, "pkg/cli.py", CLI)
    fact, why = store.add(proposal(source=quoting(
        "6", '    return f\\"{entry.status // 10}xx\\"')), record)
    assert fact is None
    assert why == ('the evidence does not hold: "return f\\"{entry.status //'
                   ' 10}xx\\"" is not at pkg/cli.py:6')


def test_evidence_cut_at_a_quote_inside_it_is_refused(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    put(tmp_path, "pkg/cli.py", CLI)
    # read to its first quote, `return f` is at the line, and the words after
    # the last quote would hide that the rest of it is not
    fact, why = store.add(proposal(source=quoting(
        "6", '    return f"{entry.code}xx"') + " is the key"), record)
    assert fact is None
    assert why == ('the evidence does not hold: the quote of pkg/cli.py:6'
                   ' stops at a " inside it, so it is cut short')
    fact, why = store.add(proposal(
        source=quoting("6", "    return f") + ' is the key"'), record)
    assert fact is None


def test_a_quote_with_words_after_it_still_holds(tmp_path):
    store, record = a_store(tmp_path, cap=9)
    fact, why = store.add(proposal(
        source='seq 2 worker.md; evidence: pkg/a.py:5 "raise ValueError"'
               " (the empty-line path)"), record)
    assert why == "" and fact is not None


def test_a_proposal_with_no_evidence_the_runner_can_check_is_refused(
        tmp_path):
    store, record = a_store(tmp_path)
    for source in ("seq 2 worker.md", "seq 2 worker.md; evidence: it is so"):
        fact, why = store.add(proposal(source=source), record)
        assert fact is None
        assert why.startswith("the evidence does not hold"), why


def test_command_and_ruling_evidence_hold_only_when_on_record(tmp_path):
    store, record = a_store(tmp_path, cap=9,
                            ran=[("python -m pytest -q", 1)],
                            stamps=["2026-10-19 14:31"])
    ok, why = store.add(proposal(
        source="seq 3 worker.md; evidence: python -m pytest -q exit 1"),
        record)
    assert why == ""
    _, why = store.add(proposal(
        claim="a second one",
        source="seq 3 worker.md; evidence: python -m pytest -q exit 0"),
        record)
    assert why == ("the evidence does not hold: no gate in this run ran"
                   " `python -m pytest -q` to exit 0")
    _, why = store.add(proposal(
        claim="a third one",
        source="seq 3 worker.md; evidence: decisions.md 2026-10-19 14:31"),
        record)
    assert why == ""
    _, why = store.add(proposal(
        claim="a fourth one",
        source="seq 3 worker.md; evidence: decisions.md 2026-10-19 09:00"),
        record)
    assert why == ("the evidence does not hold: no ruling on record in"
                   " decisions.md at 2026-10-19 09:00")


def test_the_runner_hashes_the_anchor_itself(tmp_path):
    store, record = a_store(tmp_path)
    fact, why = store.add(proposal(anchor="pkg/a.py:3-6 sha256:" + "0" * 64),
                          record)
    assert why == ""
    want = facts.anchored(tmp_path, "pkg/a.py", 3, 6)
    assert fact.get("anchor") == str(want)
    _, why = store.add(proposal(claim="past the end", anchor="pkg/a.py:3-90"),
                       record)
    assert why == "the anchor pkg/a.py:3-90 is not lines of the file"


def test_a_scope_that_is_not_in_the_place_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    _, why = store.add(proposal(scope=["pkg/b.py"], anchor=""), record)
    assert why == "the scope pkg/b.py is not in the place"


def test_a_scope_outside_the_place_is_refused_and_nothing_is_written(
        tmp_path):
    place = tmp_path / "work" / "repo"
    store, record = a_store(place)
    put(tmp_path, "other/x.py", "x = 1" + NL)
    put(place, "README.md", "# the project" + NL + "read me" + NL)
    for scope in ("../", "../../", "../../other/", "../../other/x.py",
                  "pkg/../../", str(tmp_path / "other") + "/",
                  (tmp_path / "other").as_posix() + "/", "/", "../**",
                  "pkg/../README.md"):
        _, why = store.add(proposal(scope=[scope], anchor=""), record)
        assert why == ("the scope " + facts.norm(scope)
                       + " is outside the place"), (scope, why)
    assert sorted(p.relative_to(tmp_path).as_posix()
                  for p in tmp_path.rglob("*") if p.is_file()) == [
        "other/x.py", "work/repo/README.md", "work/repo/pkg/a.py"]
    assert (place / "README.md").read_text(encoding="utf-8") == \
        "# the project" + NL + "read me" + NL


def test_an_anchor_outside_the_place_is_refused_on_a_fact_and_a_reanchor(
        tmp_path):
    place = tmp_path / "repo"
    store, record = a_store(place)
    put(tmp_path, "secret.py", CODE)
    outside = (tmp_path / "secret.py").as_posix()
    for path in ("../secret.py", outside, "pkg/../../secret.py"):
        _, why = store.add(proposal(anchor=path + ":3-6"), record)
        assert why == "the anchor " + path + " is outside the place", \
            (path, why)
    fact, why = store.add(proposal(), record)
    assert why == ""
    for path in ("../secret.py", outside):
        why = store.reanchor(fact.id, path + ":3-6",
                             'pkg/a.py:5 "raise ValueError"', record)
        assert why == "the anchor " + path + " is outside the place", \
            (path, why)
    [kept] = facts.read(place)
    assert kept.get("anchor").startswith("pkg/a.py:3-6 ")


def test_a_claim_with_no_why_or_two_lines_or_a_pipe_is_refused(tmp_path):
    store, record = a_store(tmp_path)
    assert store.add(proposal(why=""), record)[1] == "it has no why"
    assert store.add(proposal(claim="one\ntwo"), record)[1] == \
        "the claim is more than one line"
    assert store.add(proposal(claim="a | b"), record)[1] == \
        "claim holds a |, which no taught format carries"


def test_a_hand_written_entry_present_at_the_start_counts(tmp_path):
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0001", "pkg/", "by hand"))
    store = factsguard.Store(tmp_path)
    assert [f.id for f in store.read()] == ["F-0001"]
    store.keep_in(tmp_path / "run")
    data = json.loads((tmp_path / "run" / "facts.json").read_text(
        encoding="utf-8"))
    assert len(data["found"]) == 1 and data["written"] == []


def test_the_fourth_new_fact_in_one_run_is_refused_for_the_cap(tmp_path):
    store, record = a_store(tmp_path)
    for n in range(3):
        fact, why = store.add(proposal(claim="fact number " + str(n)), record)
        assert why == "" and fact.id == "F-000" + str(n + 1)
    fact, why = store.add(proposal(claim="fact number 3"), record)
    assert fact is None
    assert why == "per-run cap: 3 new facts are already written this run"
    assert len(facts.read(tmp_path)) == 3


def test_the_same_claim_again_counts_on_the_live_fact(tmp_path):
    store, record = a_store(tmp_path)
    first, _ = store.add(proposal(), record)
    later = factsguard.Store(tmp_path)
    again, why = later.add(proposal(claim="Parse raises on an empty line,"
                                          " never returns [] "), record)
    assert why == ""
    assert again.id == first.id
    [fact] = facts.read(tmp_path)
    assert fact.get("seen") == ("proposed 2, attached 0, honoured 0,"
                                " contradicted 0")
    assert later.new == 0


def test_a_line_written_by_hand_in_an_entry_survives_a_runner_rewrite(
        tmp_path):
    store, record = a_store(tmp_path)
    old, _ = store.add(proposal(), record)
    path = tmp_path / "facts" / "pkg" / "a.py.md"
    text = path.read_text(encoding="utf-8")
    by_hand = text.replace("kind: why" + NL, "kind: why" + NL
                           + "this bit us twice, see the release notes" + NL
                           + NL + "- ask before changing it" + NL)
    by_hand = by_hand.rstrip(NL) + NL + NL + "a note at the end" + NL
    path.write_text(by_hand, encoding="utf-8", newline=NL)
    later = factsguard.Store(tmp_path)
    again, why = later.add(proposal(), record)
    assert why == "" and again.id == old.id
    _, why = later.add(proposal(claim="a second fact on the file"), record)
    assert why == ""
    after = path.read_text(encoding="utf-8")
    for line in ("this bit us twice, see the release notes",
                 "- ask before changing it", "a note at the end"):
        assert line in after, after
    assert "proposed 2" in after
    assert after.index("- ask before changing it") < after.index("F-0002")
    assert later.check("next") == ""


def test_two_runs_on_one_place_keep_each_others_facts(tmp_path):
    put(tmp_path, "pkg/a.py", CODE)
    own = tmp_path / "runs"
    first = factsguard.Store(tmp_path, cap=9, own=own)
    second = factsguard.Store(tmp_path, cap=9, own=own)
    record = factsguard.Record(tmp_path)
    one, why = first.add(proposal(), record)
    assert why == ""
    assert second.check("worker.md") == ""
    two, why = second.add(proposal(claim="a second fact"), record)
    assert why == ""
    assert (one.id, two.id) == ("F-0001", "F-0002")
    assert first.check("worker.md") == ""
    assert sorted(f.id for f in facts.read(tmp_path)) == ["F-0001", "F-0002"]
    assert [f.id for f in second.read()] == ["F-0001", "F-0002"]
    first.attached([{"facts_attached": ["F-0001", "F-0002"]}])
    assert second.check("worker.md") == ""
    put(tmp_path, "facts/pkg/_folder.md", entry("F-0009", "pkg/", "forged"))
    said = second.check("worker.md")
    assert "added or edited F-0009" in said
    assert first.check("worker.md") == ""
    assert sorted(f.id for f in facts.read(tmp_path)) == ["F-0001", "F-0002"]
    assert "attached 1" in (tmp_path / "facts" / "pkg" / "a.py.md").read_text(
        encoding="utf-8")


def test_the_places_turn_is_held_by_one_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(factsguard, "WAIT", 0.2)
    gate = tmp_path / "runs" / "facts-ledger-x.lock"
    held = factsguard.take(gate)
    assert held is not None
    assert factsguard.take(gate) is None
    factsguard.give(held)
    again = factsguard.take(gate)
    assert again is not None
    factsguard.give(again)


def test_a_written_fact_carries_its_source_and_who_wrote_it(tmp_path):
    store, record = a_store(tmp_path)
    store.keep_in(tmp_path / "run")
    fact, _ = store.add(proposal(), record, today="2026-10-22 08:00")
    [read] = facts.read(tmp_path)
    assert read.file == tmp_path / "facts" / "pkg" / "a.py.md"
    assert read.get("source").endswith('evidence: pkg/a.py:5 "raise'
                                       ' ValueError"')
    assert read.get("written") == "2026-10-22 08:00 by runner"
    data = json.loads((tmp_path / "run" / "facts.json").read_text(
        encoding="utf-8"))
    assert [w["id"] for w in data["written"]] == [fact.id]
    assert store.check("retro.md") == ""


def test_a_supersession_keeps_the_old_fact_marked(tmp_path):
    store, record = a_store(tmp_path)
    old, _ = store.add(proposal(), record)
    new, why = store.add(proposal(claim="parse raises KeyError now",
                                  supersedes=old.id), record)
    assert why == ""
    found = dict((f.id, f) for f in facts.read(tmp_path))
    assert found[old.id].status == "superseded"
    assert found[new.id].get("supersedes") == old.id
    _, why = store.add(proposal(claim="x", supersedes="F-0099"), record)
    assert why == "it supersedes F-0099, which is not a live or stale fact"


def test_the_hook_refuses_a_write_under_the_facts_folder(tmp_path):
    keep = str(tmp_path / "facts") + "/"

    def hook(tool, given):
        data = {"tool_name": tool, "tool_input": given, "cwd": str(tmp_path),
                "session_id": "s"}
        return shellwrite.decide([str(tmp_path / "denials.jsonl"), "--keep",
                                  keep], json.dumps(data))

    code, said = hook("Write", {"file_path": str(tmp_path / "facts" / "pkg"
                                                 / "a.py.md"), "content": "x"})
    assert code == 2
    assert "facts" in said and "only the runner" in said
    assert hook("Edit", {"file_path": "facts/_project.md"})[0] == 2
    assert hook("Write", {"file_path": str(tmp_path / "factsheet.md"),
                          "content": "x"}) == (0, "")


def test_a_step_granted_write_has_the_facts_folder_kept(tmp_path):
    p = providers.build({"provider": "cli", "command": "claude"},
                        where=tmp_path, grant=["read", "write"])
    argv, _ = p.argv("hi")
    settings = json.loads(argv[argv.index("--settings") + 1])
    args = settings["hooks"]["PreToolUse"][0]["hooks"][0]["args"]
    kept = [args[i + 1] for i, a in enumerate(args) if a == "--keep"]
    assert (tmp_path.resolve() / "facts").as_posix() + "/" in kept
