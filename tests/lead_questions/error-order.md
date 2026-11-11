- behaviour: all or nothing across files. a.csv is valid and b.csv has a bad amount on line 4. `import a.csv b.csv` gives stderr `error: b.csv: line 4: <reason>`, empty stdout, exit 2. An existing store stays byte for byte unchanged; a missing store is not created
  file: ledgerlite/importer.py
  spec: adds to TASK.md:88
- open: when an earlier file has a currency or line error and a later file is unreadable or malformed, the spec does not say which error is reported. "Read in the order given" suggests the first one met in file order, but it is not stated whether every file is parsed before currency checks start (unsure)

HANDOFF
DID:
- Planned multi-file `import` as 21 testable behaviours, all of them additions to the spec or allowed by it. I found no conflict
DOUBTS:
- When several files have errors, which one is reported: the first in file order, or every parse error before any currency error
QUESTION: When an earlier file has a currency error and a later file has a parse error (TASK.md:80-84 do not order them across files), which error should be reported?
RECOMMEND: The first error met in file order, checking each file's parse and currency together before moving to the next file. This matches "read in the order given"
SIZE: one function in ledgerlite/importer.py
END HANDOFF
