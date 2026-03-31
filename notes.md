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

## 2025-11-30

november retro. hardening month.

what sticks
- resume. it has already saved me two full digest runs and that is real money.
- the error taxonomy. retrying a missing api key three times with backoff was
  the stupidest thing this has ever done.
- the state clobber fix. one file per flow and the whole class of problem goes
  away. i found it wiring resume, which is the only reason i found it.
- pytest. the hand run asserts were fine until they were not.

what does not
- eight calls and six minutes for one digest, and i still have no number for
  what that costs.
- a fanned out worker can die and the merge stitches around the hole without
  saying anything.
- flow.yaml says what the steps are. it still says nothing about what the flow
  is supposed to produce.

## 2025-12-02

a flow should promise something.

    promises:
      inputs: a folder of .md files
      outputs: three lists - changed, needs-me, can-wait
      invariants:
        - no file appears in two lists
        - needs-me is at most 5 lines
        - every line names a file

inputs and outputs are documentation, which is worth something on its own -
six months from now i will not remember what release-notes expects.

invariants are the bit with teeth. they are already written down, in prose, in
instructions.md, and the reviewer is the only thing checking them. if they were
in the spec then something other than a prompt could check them, and a failure
could say WHICH promise broke instead of me reading the output and squinting.

## 2025-12-12

ops-check promises are harder to write than the digest ones.

the digest was easy because its output has a shape. three lists, no file twice,
needs-me under five. i can say those.

ops-check promises "only tell me what is wrong", and i cannot write that as an
invariant. every version i try is either useless (findings are findings) or a
lie (every finding is real - no, i want it to guess sometimes, i would rather
see a maybe than miss an outage).

the honest promise might be about what it must NOT do. never says something is
fine. never reports a line the log does not contain. leaving it for now.

## 2025-12-14

spec first is the pattern that survived.

seven months of this and nearly everything has been rewritten. bash went.
frontmatter went. the fragment loader is on its second life and about to be on
its third. two flows were deleted outright.

what did not change: write down what the thing has to do before writing the
thing. the flow file came before the runner read it. the prompt rules came
before the fragments. the promises block is the same move again, one level up.

it is the only habit here that has not needed a rewrite, and it is the one i
brought with me rather than learned doing this.

## 2025-12-19

year one, roughly. started this in may.

six flows. two deleted along the way and i do not miss either. the runner is
about eight hundred lines and four of them are the ones i would defend.

the shape it settled into, which i did not plan:

    a flow is a spec. the spec says what it promises.
    the steps are roles. the roles argue.
    every run is written down. a run that dies can be picked up.
    nothing that costs money happens without a cap on it.

none of that was the idea in may. in may the idea was to stop pasting the same
prompt into a terminal twice a week.

what is still wrong: i have no number for what a run costs. i have no way to
tell whether last week's output was better or worse than this week's, only
whether it looked fine when i read it. those are the same problem wearing two
hats and it is next year's.

## 2026-01-30

january. spent it making this legible rather than adding to it.

the router is the one thing i would call a change. the step list has been a
straight line since july and the reviewer sending work back was a special case
bolted onto the side of the loop. now the flow says where a verdict sends you
and the runner asks. the loop got shorter, which is usually the sign.

the pydantic thing is not going well. it validates beautifully and then i need
promises.as_prompt() and i am back to wrapping the models in my own classes,
which is the thing i was trying to delete. one more evening on it.

## 2026-02-10

dropped pydantic.

it validates better than my thirty lines and i am still deleting it. every
place downstream wants spec.promises.as_prompt(), spec.get(), spec["steps"] -
behaviour, not just fields. with pydantic i either hang methods off the models,
which is a config library doing domain work, or i wrap them in the classes i
already have, which is what i was trying to delete.

so the wrapper stays and check() stays. one dependency, still.

## 2026-02-28

february. the month it learned to say no.

the spend cap is the one i should have built in august. nine months of running
this with no ceiling and the only reason nothing went wrong is that nothing
went wrong. the cache made it worse before it made it better - i was counting
cached calls against the cap, so a flow with a redo in it hit the ceiling on
work it had not done.

the promise checking is smaller than it sounds and i want to keep it that way.
it can check three shapes. everything else it says it cannot check, which is
the honest answer and the one i would rather have than a tick i do not believe.

repo-audit is the one i actually use now. twenty files, one worker each, and a
merge that tells me where the risk is. i have pointed it at two of my own
things and both times it found something in the second half of the list that i
would not have looked at.

## 2026-03-02

a check step that isnt a prompt.

the promise checker knows three shapes and says "not checkable" to everything
else, which is honest and not much use. the things i actually want to assert
are not shapes at all:

- does this markdown parse
- is every path in this output a file that exists
- does the test in this patch actually fail before the patch

none of those want a model. they want a program. and i keep almost writing
them into promises.py, where they do not belong, because promises.py is about
the flow's own declared invariants and these are just checks.

so: a check step is a thing with a name and a run(text) that says pass or fail
and why. the flow lists which ones it wants. one of them can be "run this
command and look at the exit code", which is the whole point, because then
anything that has a cli can be a check without me writing an adapter for it.

## 2026-03-24

dropped jinja too. second dependency i have tried and put back this year.

it does what it says. the problem is what it does to the prompts: a role file
stops being markdown a person reads and becomes a template that happens to
render markdown. a stray brace in an example breaks a run, and half my prompts
have examples with braces in them.

the actual complaint was that fragments are all-or-nothing, and the per-role
EXTRA map already solved that in october. i went looking for a library to
replace a working seven-line dict.

so: str.replace for the env substitution, the EXTRA map for the per-role bits,
nothing new in requirements. i did look at string.Template on the way past and
it is worse here - every dollar in a prompt would need escaping.

## 2026-03-28

gates should be tools, not prompts.

i spent nine months making the reviewer better at saying no. better prompt,
more specific rules, a verdict line, a send-back loop. all of it helped and
none of it is reliable, because it cannot be: it is a model being asked to be
careful, and some days it is.

a regex either matched or it did not. an exit code is an exit code.

the split i would keep: the model is for the things only a model can do -
reading, judging, writing. the gate is for everything with a yes or no answer.
every time i have asked a prompt to do a gate's job it has worked most of the
time, which is the worst possible outcome, because that is the failure mode you
stop looking for.

## 2026-03-31

long runs cost more than i thought, and now i can see it.

repo-audit on something real is twenty files, one worker each, plus a planner,
a merge and a reviewer. twenty three calls and about a hundred and eighty
thousand tokens on the rough count. i have been running it two or three times a
week on the thing i am building, and once more each time i change the plan and
want a fresh read.

that is the most expensive flow i have and it is also the most useful, which is
an annoying combination.

what i have done about it: the planner caps at twenty files, the flow declares
its own ceiling, and the cache means a re-run after a prompt tweak only pays
for the steps that changed. what i have not done is anything about the fact
that i am asking a model to read the same files every time, when almost none of
them changed since the last read.
