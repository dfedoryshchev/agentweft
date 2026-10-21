## seq 4 worker.md
failed: the command gate: tests/test_export.py::test_export_keeps_decimal_mark, export wrote "." for a "," ledger
why: the option stopped one layer short: money.fmt has no decimal_mark parameter, so export could not honour it
change: cashbook/money.py:19 fmt gains decimal_mark; cashbook/export.py passes it

## change first
cashbook/money.py:19 fmt takes decimal_mark, as parse_amount does

FACTS
fact:
  scope: cashbook/money.py
  kind: why
  label: important
  claim: parse_amount and fmt take the same decimal_mark; a new number option is carried through both
  why: this run's export failure: the option reached parse_amount but not fmt
  source: seq 4 worker.md; evidence: TASK.md:4 "money.fmt(value, decimal_mark)"
  anchor: cashbook/money.py:12-22
guard: seq 4
  kind: test
  where: tests/test_money.py
  what: fmt(parse_amount(x, m), m) gives x back for both marks
END FACTS
