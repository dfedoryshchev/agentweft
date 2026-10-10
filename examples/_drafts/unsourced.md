The importer failed on all 412 rows and wrote nothing.

Empty rows caused both failures.

Each retry ran the whole file again, which made the outage last 6 minutes.

Skipping empty rows would cut the run time by more than half.
