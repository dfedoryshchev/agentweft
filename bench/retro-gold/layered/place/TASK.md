# cashbook: import, keep and export a ledger

## 1. amounts
an amount is read with money.parse_amount(text, decimal_mark) and written with money.fmt(value, decimal_mark).
--decimal-mark , reads and writes "1,50"; the default is ".".

## 2. layers
cli.py takes the options and hands them to importer.py and export.py; neither reads the command line itself.
