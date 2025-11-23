# notes

## 2025-05-30

week one. two flows.

what worked
- the check step. it caught itself inventing a number in the summary, twice.
  splitting summarise and check into two passes is the whole trick i think.
- keeping the prompt in a file instead of in my shell history

what didnt
- the cli times out on the big folder and i lose the whole run
- i am pasting the same "output markdown, nothing else" line into every flow
- hardcoded paths everywhere, if i move the folder its all broken

## 2025-06-20

the chaining thing works better than i expected. the digest draft goes in as
plain text at the bottom of the critique prompt and it just picks it up. no
json, no structure, nothing clever.

things i keep hitting
- every flow wants the same three lines at the top about markdown only and no
  preamble. i am copying them by hand into every instructions.md
- when a step fails halfway i lose the first step too and have to rerun the lot
- runs/ is going to get big

## 2025-06-29

june retro. four flows, one runner, run.sh gone.

what sticks
- two passes beats one prompt, every single time. draft then critique.
- the shared header fragment. should have done it in week two.
- keeping the rules in a separate file from the prompt. i can change how it
  behaves without touching what it does.

what does not
- competitor-watch. i have narrowed it twice and it still tells me things i do
  not care about. i think the flow is wrong, not the prompt.
- naming. flows/, fragments/, runs/. i have renamed the flow folder three times
  and i will probably do it again.
- no idea which runs failed without opening them

## 2025-07-12

roles that argue produce better output. i did not expect that.

the reviewer is the same model with a different prompt, and it still catches
the worker inventing things, because it is not the one that wrote them. one
model doing summarise-then-check in a single pass defends its own text. two
passes with different instructions does not.

the planner matters less than i thought. mostly it stops the worker starting
in the middle.

## 2025-07-25

july retro. roles happened.

what sticks
- planner / worker / reviewer. the reviewer is the one that earns its keep.
- frontmatter. the step list living in the flow instead of in runner.py means
  i can add a flow without touching python.
- fragments/. three files now, and every role picks them up for free.

what does not
- runs/ is a pile. the index helps but it is not sorted and i cannot tell a
  failed run from a good one without opening it.
- the retry thing does not feel right. it gives up too early on long runs and
  i have not worked out why yet.
- competitor-watch is still here and i still do not read its output.

## 2025-08-13

state makes diffs possible and i did not see that coming.

ops-check used to tell me the same six things every morning because it had no
idea it had already told me. now the planner gets handed the last run and only
plans around what is new. the output went from a page to four lines.

the digest could do the same with "what changed since the last digest" but the
planner already reads mtimes so it is less obvious there.

## 2025-08-30

august retro. two weeks off in the middle of it.

what sticks
- one runner. the fan-out experiment folded back in behind a flag in the flow
  file, which is where that decision belongs.
- state. four lines of json and it changed what ops-check is for.
- the workers run at the same time now. the digest went from ninety seconds to
  about twenty five.

what does not
- coming back after two weeks and finding four prompts had quietly drifted
  apart. hoisting the shared rule up into fragments/ helped but each flow still
  has its own tone.
- i still cannot resume a run that died in the middle. if the reviewer times
  out i rerun the planner and the workers for nothing, and that is real money.
- no idea what any of this costs me per run.

## 2025-09-01

the frontmatter parser is mine and i keep patching it. colons, then blank
lines, then a value with a hash in it. this is a solved problem and i am
solving it again badly.

flow.yaml instead. one file per flow, proper yaml, and the step list stops
being a comma separated string i split by hand:

    name: weekly digest
    steps:
      - role: planner
      - role: worker
        fanout: true
      - role: merge
      - role: reviewer
    timeout: 300

that also gives me somewhere to hang per step settings later.

## 2025-09-21

config beats convention for flows.

the frontmatter parser was convention: everything in a fixed shape, and every
time i wanted something new i added another rule to the parser. flow.yaml is
config: the flow says what it is, the runner reads it, and adding a field costs
nothing.

release-notes took about ten minutes to add and i did not open runner.py once.
that is the first time that has been true.

## 2025-10-12

what should a flow spec actually promise.

flow.yaml says what the steps ARE. it says nothing about what the flow is for
or what counts as it having worked. when a run comes back wrong i read the
output and guess, every time.

the rules that matter are the ones i already write into instructions.md as
prose and hope for: the digest never repeats a file in two lists, release-notes
never mentions a commit hash, ops-check never says something is fine. those are
checkable. they are just not anywhere a machine can see them.

not building this yet. writing it down so i stop re-deciding it.

## 2025-10-30

october retro. mostly tidying, one thing moved out.

what sticks
- runner/ as a package. main() was doing eight jobs and now it does one.
- the Run object. i was passing fm into everything so two functions could read
  a timeout out of it.
- moving the general conventions to their own repo. they were never about this
  project and i kept editing them twice.

what does not
- two loaders for the same job. fragments/ and skills/ both end up
  concatenated onto every prompt and i have written that concatenation twice.
  one of them has to go, i just do not know which yet.
- still no way to rerun the bit that failed. it has been on this list since
  august, and every reviewer redo pays for the whole flow again.

## 2025-11-09

resume knows WHICH step died. it does not have what that step was given.

every step gets the previous step's output appended to its prompt, and that
output only ever lived in a variable. when the run dies the variable dies with
it. so resume can tell me "it fell over at merge" and then has nothing to hand
merge.

runs/last-step.md is close but it is one file for all flows and it gets
overwritten every step. needs to be per run, per step.

## 2025-11-23

what breaks in a long run.

the digest with a full inbox is four steps and four fanned out workers, so
eight calls, and about six minutes. things that have gone wrong in that window,
in order of how annoying they were:

- the cli times out on one worker and the merge gets a hole in it. the merge
  does not know a part is missing so it stitches five where there should be six
  and nothing anywhere says so.
- a redo doubles the whole thing. two goes and i have paid for the flow three
  times.
- i cannot tell any of that from the output. it looks like a normal digest.

the handoff object has a meta dict now and nothing puts anything in it. that is
where the count should go.
