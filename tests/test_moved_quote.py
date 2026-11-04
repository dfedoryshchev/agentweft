"""a quote of a spec line the run left as it was, cited where it is now.

under `spec_files: additions` a step may add lines to a spec file, and a
line it left as it was then sits lower. a `spec:` line on a WRONG TEST
claim that quotes that line, word for word, at its number now is found:
the line is mapped back to where the run found it. a line the run rewrote
or added is never found that way, and a text at neither number still
fails the quote check.
"""
import sys

sys.path.insert(0, ".")
from agentweft.guardrails import snapshot, specfiles
from agentweft.runner import ruling, wrongtest

import test_spec_files as sf

NL = chr(10)
ADDED = "the report also counts them."
ABOVE = "# report" + NL + NL + ADDED + NL + sf.LINE + NL
START_TEST = "tests/test_report.py::test_alphabetical"


def claim(cite, quote):
    return ("WRONG TEST: " + START_TEST + NL + "why: it wants a sorted list"
            + NL + "spec: " + cite + ' "' + quote + '"' + NL)


def test_a_claim_quoting_a_line_by_its_number_now_parks_on_the_claim(
        tmp_path, monkeypatch):
    place = sf.a_place(tmp_path / "repo")
    sf.flow_with(tmp_path, "additions")
    does = sf.worker_writes(ABOVE)
    writes, said = does["worker.md"]
    does["worker.md"] = (writes, said + NL + claim("TASK.md:4", sf.LINE))
    code, called = sf.running(tmp_path, monkeypatch, place, does, False)
    folder = sf.folders()[-1]
    gates = sf.read(folder / "gates.md")
    assert "FAIL quote" not in gates, gates
    assert called == ["tester.md", "worker.md"]
    question = sf.read(folder / "question.md")
    assert "worker.md says " + START_TEST + " is wrong" in question
    assert "TASK.md:4" in question


def test_a_quote_at_neither_number_still_fails(tmp_path, monkeypatch):
    place = sf.a_place(tmp_path / "repo")
    sf.flow_with(tmp_path, "additions")
    does = sf.worker_writes(ABOVE)
    writes, said = does["worker.md"]
    does["worker.md"] = (writes, said + NL + claim(
        "TASK.md:4", "the report lists students by age."))
    code, called = sf.running(tmp_path, monkeypatch, place, does, False)
    assert code != 0
    assert "FAIL quote" in sf.read(sf.folders()[-1] / "gates.md")


def test_the_map_pairs_only_lines_the_run_left_as_they_were():
    rewritten = "# report" + NL + NL + ADDED + NL + sf.REWRITTEN + NL
    assert specfiles.stayed(sf.SPEC, ABOVE) == {1: 1, 2: 2, 4: 3, 5: 4}
    assert 4 not in specfiles.stayed(sf.SPEC, rewritten)
    assert 3 not in specfiles.stayed(sf.SPEC, ABOVE)


def test_a_rewritten_line_is_not_found_through_the_map(tmp_path):
    place = sf.a_place(tmp_path / "repo")
    start = snapshot.take(place)
    (place / "TASK.md").write_text("# report" + NL + NL + ADDED + NL
                                   + sf.REWRITTEN + NL, encoding="utf-8")
    assert ruling.moved_to(place, "TASK.md", 4, 4, ruling.flat(sf.REWRITTEN),
                           start) is None
    assert ruling.misquote('TASK.md:4 "' + sf.REWRITTEN + '"', place, start)


def test_a_conflict_on_a_line_the_run_added_still_fails(tmp_path,
                                                       monkeypatch):
    place = sf.a_place(tmp_path / "repo")
    sf.flow_with(tmp_path, "additions")
    does = sf.worker_writes(ABOVE)
    writes, said = does["worker.md"]
    does["worker.md"] = (writes, 'CONFLICT: TASK.md:3 "' + ADDED + '"' + NL
                         + "request: count them" + NL)
    code, _ = sf.running(tmp_path, monkeypatch, place, does, False)
    assert code != 0
    assert "which is not at TASK.md:3 as the run found it" in sf.read(
        sf.folders()[-1] / "gates.md")


def test_the_claim_check_reads_the_moved_line(tmp_path):
    place = sf.a_place(tmp_path / "repo")
    start = snapshot.take(place)
    (place / "TASK.md").write_text(ABOVE, encoding="utf-8")
    assert wrongtest.misquoted(claim("TASK.md:4", sf.LINE), place,
                               start) == ""
    assert wrongtest.misquoted(claim("TASK.md:3", ADDED), place, start)
    assert ruling.moved_to(place, "TASK.md", 4, 4, ruling.flat(sf.LINE),
                           start) == (3, 3)
    assert ruling.moved_to(place, "TASK.md", 3, 3, ruling.flat(ADDED),
                           start) is None


def test_a_ruling_on_the_line_covers_a_claim_citing_where_it_moved(tmp_path):
    place = sf.a_place(tmp_path / "repo")
    start = snapshot.take(place)
    (place / "TASK.md").write_text(ABOVE, encoding="utf-8")

    def ruled(rel, line):
        return "the override" if line.rstrip() == sf.LINE else None
    spec = 'TASK.md:4 "' + sf.LINE + '"'
    assert ruling.ruled_quote(spec, place, start, ruled) == "the override"
    assert ruling.ruled_quote(spec, place, start,
                              lambda rel, line: None) is None
