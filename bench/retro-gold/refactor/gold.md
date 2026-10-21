## seq 2 worker.md
failed: the command gate: tests/test_stats.py::test_p50_of_five gave 2 for the values 1 to 5, wanted 3
why: the extraction replaced the ceiling with round(), which rounds half to even: round(2.5) is 2 where ceil(2.5) is 3; TASK.md section 4 fixes ceil
change: logcount/stats.py nearest_rank - rank = math.ceil(p * len(values) / 100)

## change first
logcount/stats.py nearest_rank - math.ceil, never round()

FACTS
fact:
  scope: logcount/stats.py
  kind: convention
  label: important
  claim: nearest_rank is ceil(p / 100 x count), 1-based, never round()
  why: TASK.md section 4; round() broke p50 of five values in this run
  source: seq 2 worker.md; evidence: TASK.md:14 "rank = ceil(N / 100 x count), 1-based"
  anchor: logcount/stats.py:5-8
guard: seq 2
  kind: test
  where: tests/test_stats.py
  what: p50 of 1 to 5 is 3 and p90 of 1 to 10 is 9
END FACTS
