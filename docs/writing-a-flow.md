# writing a new flow

copy `flows/_template` and rename it. that is most of it.

    cp -r flows/_template flows/my-flow

## 1. say what it is for, in one line

put it at the top of `instructions.md`. if you cannot write that line the flow
is not ready to exist yet. every flow i have deleted failed this test first and
i ignored it.

## 2. write the planner before the worker

the planner reads and decides, the worker does. the temptation is to skip the
planner for a small flow, and every time i have done that the worker starts in
the middle of the input and never recovers.

## 3. keep the shared rules out

do not put "markdown only" in your role prompts. it is already in
`fragments/`. only put rules in `instructions.md` that are true for this flow
and not for the others.

## 4. give the reviewer something to disagree with

a reviewer that just reads nicely written output agrees with it. the ops-check
reviewer works because its prompt lists the specific things that are NOT
findings. be that specific or skip the reviewer.

## 5. run it three times before you trust it

    python runner.py my-flow --force

the first run tells you the prompt is wrong. the second tells you the output
shape is wrong. the third is the first one worth reading.
