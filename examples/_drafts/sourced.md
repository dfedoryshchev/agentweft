VERDICT: ok

According to the importer log, it started on 412 rows and finished with 0 rows written.

As the log records, row 118 was empty and skipped just before the first failure.

Per the same log, both failures are the same error, no columns to parse, and it finished after retry 2 of 3.

Nothing in the log says how long a run without the empty rows would take, so the time saving is cut.
