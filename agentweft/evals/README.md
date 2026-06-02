# evals

fixed inputs, so a prompt change can be compared to the one before it.

    python -m evals weekly-digest

a case is a folder under `evals/<flow>/cases/`: an `inbox/` of files and a
`case.yaml` saying what has to hold. there is no expected output. the output is
not deterministic and a golden file would be wrong by wednesday.

what a case asserts is the flow's own promises - the same invariants the
runner already checks - plus what it cost.
