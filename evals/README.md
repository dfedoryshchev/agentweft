# evals

fixed inputs, so a prompt change can be compared to the one before it.

    python -m agentweft.evals weekly-digest

a case is a folder under `evals/<flow>/cases/`: an `inbox/` of files and a
`case.yaml` saying what has to hold. there is no expected output. the output is
not deterministic and a golden file would be wrong by wednesday.

what a case asserts is the flow's own promises - the same invariants the runner
already checks - plus what it cost.

## the comparison

the last scores are kept in `evals/.last.json` and every run prints what
changed:

    since the last scored run:
      quiet-week          same   (2/2 -> 2/2)
      busy-week           WORSE -1  (2/2 -> 1/2)  tokens +4100

that is the number i did not have for the first year of this. every prompt
change before it was judged by reading one output and deciding it looked
better.

`--no-save` runs without overwriting the baseline.
