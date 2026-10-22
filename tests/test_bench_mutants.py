"""each test a run adds is scored by the mutants of the fix it kills.

sixteen tests that all die on the same one deleted line are one test written
sixteen times. the bench cannot see that from a pass count; it can from the
set of mutants each test kills.
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
from agentweft.bench import mutants

BEFORE = '''def add(entries, amount):
    entries.append(amount)
    return entries


def clean(note):
    return note
'''
AFTER = '''def add(entries, amount):
    if amount < 0:
        raise ValueError("negative")
    entries.append(amount)
    return entries


def clean(note):
    note = note.strip()
    return note
'''
SAME = '''

def test_clean_strips_{i}():
    assert ledger.clean("  note {i}  ") == "note {i}"
'''
APART = '''

def test_a_negative_amount_is_refused():
    with pytest.raises(ValueError):
        ledger.add([], -1)


def test_an_amount_of_zero_is_kept():
    assert ledger.add([], 0) == [0]


def test_a_plain_note_is_left_alone():
    assert ledger.clean("note") == "note"
'''
STRIPS = ["test_clean_strips_" + str(i) for i in range(16)]


def project(tmp_path):
    start, place = tmp_path / "start", tmp_path / "place"
    start.mkdir()
    place.mkdir()
    (start / "ledger.py").write_text(BEFORE, encoding="utf-8")
    (place / "ledger.py").write_text(AFTER, encoding="utf-8")
    tests = "import pytest\n\nimport ledger\n" + "".join(
        SAME.format(i=i) for i in range(16)) + APART
    (place / "test_ledger_new.py").write_text(tests, encoding="utf-8")
    return start, place


def named(cases, name):
    found = [c for c in cases if c.endswith("::" + name)]
    assert len(found) == 1, (name, cases)
    return found[0]


def test_sixteen_tests_that_die_on_one_line_are_one_signature(tmp_path):
    start, place = project(tmp_path)
    got = mutants.score(start, place)
    kills = got["tests"]
    assert len(kills) == 19
    strips = [named(kills, n) for n in STRIPS]
    assert len({tuple(kills[t]) for t in strips}) == 1
    assert kills[strips[0]]
    refused = named(kills, "test_a_negative_amount_is_refused")
    zero = named(kills, "test_an_amount_of_zero_is_kept")
    sigs = {tuple(kills[t]) for t in (strips[0], refused, zero)}
    assert len(sigs) == 3
    assert got["signatures"] == 3
    assert got["duplicates"] == [sorted(strips)]
    assert got["duplicate_at"] == mutants.DUPLICATE_AT


def test_a_test_green_without_the_fix_that_kills_nothing_is_a_pin(tmp_path):
    start, place = project(tmp_path)
    got = mutants.score(start, place)
    plain = named(got["tests"], "test_a_plain_note_is_left_alone")
    assert got["tests"][plain] == []
    assert got["pins"] == [plain]
    zero = named(got["tests"], "test_an_amount_of_zero_is_kept")
    assert zero not in got["pins"]


def test_the_report_prints_signatures_groups_pins_and_the_threshold(tmp_path):
    start, place = project(tmp_path)
    text = "\n".join(mutants.lines(mutants.score(start, place)))
    assert "distinct signatures 3" in text
    assert "duplicate threshold " + str(mutants.DUPLICATE_AT) in text
    assert "16 tests, one signature" in text
    pins = text.split("pins 1\n")[1].splitlines()[0].strip()
    assert pins.endswith("::test_a_plain_note_is_left_alone")
    assert "|" not in text


def test_mutants_touch_only_the_changed_lines(tmp_path):
    start, place = project(tmp_path)
    built = mutants.build(start, place)
    names = [m["name"] for m in built]
    assert names[0] == "unpatch"
    assert built[0]["files"] == {"ledger.py": BEFORE}
    assert "hunk ledger.py:2" in names and "hunk ledger.py:9" in names
    for m in built:
        assert set(m["files"]) == {"ledger.py"}
        assert m["files"]["ledger.py"] != AFTER
    unchanged = [i + 1 for i, line in enumerate(AFTER.splitlines())
                 if line in BEFORE.splitlines()]
    made = [m for m in built if not m["name"].startswith(("unpatch", "hunk"))]
    assert made
    for m in made:
        line = int(m["name"].split(":")[1].split()[0])
        assert line not in unchanged, m["name"]
    kinds = {m["name"].split()[1] for m in made}
    assert {"flip", "const", "negate", "delete", "swap"} <= kinds


def test_the_mutant_set_is_the_same_every_time_and_capped(tmp_path):
    start, place = project(tmp_path)
    first = mutants.build(start, place)
    assert first == mutants.build(start, place)
    few = mutants.build(start, place, most=3)
    made = [m for m in few if not m["name"].startswith(("unpatch", "hunk"))]
    assert len(made) == 3
    assert few == mutants.build(start, place, most=3)
    assert [m["name"] for m in made] == sorted(
        (m["name"] for m in made), key=[x["name"] for x in first].index)


def test_a_fix_that_changes_no_source_has_nothing_to_mutate(tmp_path):
    start, place = project(tmp_path)
    (place / "ledger.py").write_text(BEFORE, encoding="utf-8")
    got = mutants.score(start, place)
    assert got["mutants"] == []
    assert "nothing to mutate" in "\n".join(mutants.lines(got))


def test_a_line_with_a_non_ascii_character_is_cut_where_the_node_is(tmp_path):
    start, place = tmp_path / "start", tmp_path / "place"
    start.mkdir()
    place.mkdir()
    (start / "tag.py").write_text('def tag(n):\n    return n\n',
                                  encoding="utf-8")
    (place / "tag.py").write_text(
        'def tag(n):\n    s = "\\u00e9"; n = n if n < 0 else 0\n    return n\n'
        .encode().decode("unicode_escape"), encoding="utf-8")
    built = {m["name"]: m["files"]["tag.py"]
             for m in mutants.build(start, place)}
    flips = [text for name, text in built.items() if " flip " in name]
    assert flips == ['def tag(n):\n    s = "\u00e9"; n = n if n <= 0 else 0\n'
                     '    return n\n']


def test_a_mutant_that_never_ends_is_killed_not_waited_on(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(mutants, "TIMEOUT", 2)
    monkeypatch.setattr(mutants, "SLOWER", 3)
    start, place = tmp_path / "start", tmp_path / "place"
    start.mkdir()
    place.mkdir()
    (start / "count.py").write_text("def count(n):\n    return 0\n",
                                    encoding="utf-8")
    (place / "count.py").write_text(
        "def count(n):\n    i = 0\n    while i < n:\n        i += 1\n"
        "    return i\n", encoding="utf-8")
    (place / "test_count.py").write_text(
        "import count\n\n\ndef test_count():\n    assert count.count(3) == 3\n",
        encoding="utf-8")
    got = mutants.score(start, place)
    assert "count.py:4:8 delete" in got["tests"]["test_count::test_count"]


def test_a_shared_signature_over_too_few_mutants_is_not_a_duplicate(tmp_path):
    start, place = tmp_path / "start", tmp_path / "place"
    start.mkdir()
    place.mkdir()
    (start / "calc.py").write_text("def add(a, b):\n    return a\n",
                                   encoding="utf-8")
    (place / "calc.py").write_text("def add(a, b):\n    return a + b\n",
                                   encoding="utf-8")
    (place / "test_calc.py").write_text(
        "import calc\n\n\ndef test_adds():\n    assert calc.add(1, 2) == 3\n"
        "\n\ndef test_zero_left():\n    assert calc.add(0, 5) == 5\n",
        encoding="utf-8")
    got = mutants.score(start, place)
    kills = got["tests"]
    assert kills["test_calc::test_adds"] == kills["test_calc::test_zero_left"]
    assert len(got["mutants"]) < mutants.MINIMUM
    assert got["duplicates"] == []
    assert got["undecided"] == [["test_calc::test_adds",
                                 "test_calc::test_zero_left"]]
    text = "\n".join(mutants.lines(got))
    assert "not enough mutants to judge" in text
    assert "likely duplicate" not in text
    assert (place / "test_calc.py").read_text(encoding="utf-8").count(
        "def test_") == 2


def test_a_shared_signature_over_enough_mutants_is_a_likely_duplicate(
        tmp_path):
    start, place = project(tmp_path)
    got = mutants.score(start, place)
    assert len(got["mutants"]) >= mutants.MINIMUM
    assert got["undecided"] == []
    text = "\n".join(mutants.lines(got))
    assert "minimum to judge " + str(mutants.MINIMUM) in text
    assert "likely duplicate groups 1" in text


def a_change(tmp_path, before, after, tests):
    start, place = tmp_path / "start", tmp_path / "place"
    for where, texts in ((start, before), (place, dict(after, **tests))):
        where.mkdir(parents=True)
        for rel, text in texts.items():
            (where / rel).write_text(text, encoding="utf-8")
    return start, place


def test_a_mutant_that_breaks_one_test_files_import_kills_only_its_tests(
        tmp_path):
    start, place = a_change(
        tmp_path, {"a.py": "def f():\n    return 1\n", "b.py": "y = 0\n"},
        {"a.py": "def f():\n    return 2\n", "b.py": "y = 0\nx = 1\n"},
        {"test_a_new.py": "import a\n\n\ndef test_f():\n"
                          "    assert a.f() == 2\n",
         "test_b_new.py": "from b import x\n\n\ndef test_x():\n"
                          "    assert x == 1\n"})
    got = mutants.score(start, place)
    kills = got["tests"]["test_a_new::test_f"]
    assert kills and not [m for m in kills if "b.py" in m], got["tests"]
    assert [m for m in got["tests"]["test_b_new::test_x"] if "b.py" in m]


def test_a_folder_named_build_above_the_root_does_not_hide_its_files(
        tmp_path):
    root = tmp_path / "build" / "start"
    (root / "dist").mkdir(parents=True)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "dist" / "b.py").write_text("y = 1\n", encoding="utf-8")
    assert mutants.files(root) == {"a.py": "x = 1\n"}


def test_mutants_no_test_kills_do_not_count_toward_the_minimum(tmp_path):
    start, place = a_change(
        tmp_path, {"calc.py": "def add(a, b):\n    return a\n"},
        {"calc.py": "def add(a, b):\n    unused = 7\n    return a + b\n"},
        {"test_calc.py": "import calc\n\n\ndef test_adds():\n"
                         "    assert calc.add(1, 2) == 3\n\n\n"
                         "def test_zero_left():\n"
                         "    assert calc.add(0, 5) == 5\n"})
    got = mutants.score(start, place, least=4)
    assert len(got["mutants"]) >= 4
    kills = got["tests"]
    assert len(kills["test_calc::test_adds"]) < 4
    assert got["duplicates"] == [], got
    assert got["undecided"] == [["test_calc::test_adds",
                                 "test_calc::test_zero_left"]]
    text = "\n".join(mutants.lines(got))
    assert "not enough mutants to judge, " + str(
        len(kills["test_calc::test_adds"])) + " of 4" in text


def test_a_new_test_whose_kills_the_old_suite_already_makes_owns_none(
        tmp_path):
    old = "import calc\n\n\ndef test_adds():\n    assert calc.add(1, 2) == 3\n"
    start, place = a_change(
        tmp_path, {"calc.py": "def add(a, b):\n    return a + b\n",
                   "test_calc.py": old},
        {"calc.py": "def add(a, b):\n    total = a + b\n    return total\n"
                    "\n\ndef neg(a):\n    return -a\n",
         "test_calc.py": old},
        {"test_calc_new.py": "import calc\n\n\ndef test_adds_two():\n"
                             "    assert calc.add(2, 2) == 4\n\n\n"
                             "def test_negates():\n"
                             "    assert calc.neg(3) == -3\n"})
    got = mutants.score(start, place)
    adds = "test_calc_new::test_adds_two"
    assert got["tests"][adds]
    assert got["suite"] == 1
    assert set(got["tests"][adds]) <= set(got["suite_kills"])
    assert got["unique"][adds] == []
    assert got["unique"]["test_calc_new::test_negates"]
    assert got["unique_kills"] == len(got["unique"][
        "test_calc_new::test_negates"])
    text = "\n".join(mutants.lines(got))
    assert "the suite it joined kills " in text
    assert "no kill of its own 1" in text
    assert "      " + adds in text


def test_no_mutant_runs_when_no_new_test_is_green_with_the_fix(
        tmp_path, monkeypatch):
    start, place = project(tmp_path)
    (place / "test_ledger_new.py").write_text(
        "import ledger\n\n\ndef test_wrong():\n"
        "    assert ledger.clean(' a ') == 'b'\n", encoding="utf-8")
    ran = []
    real = mutants.run

    def counted(*args, **kwargs):
        ran.append(args[1])
        return real(*args, **kwargs)
    monkeypatch.setattr(mutants, "run", counted)
    got = mutants.score(start, place)
    assert ran == [None]
    assert got["red_with_fix"] == ["test_ledger_new::test_wrong"]
    assert got["tests"] == {}
