# the workflow layer

there is a second thing i run on my own work, and it is not a runner. it is a
workflow: a list of phases, a named agent for each job, and two places where the
whole thing stops and waits for me. over there it lives as prose that the agents
are told to read. here it is at least a file that can be parsed.

    python run.py workflow

prints the phases, who is in each one, what it is meant to produce, and where it
stops.

## why it is in this repo

it could have been its own repo. it is not, because a phase is a flow.

a flow is an ordered list of steps, each with a role and a prompt, that produces
something and gets checked. a phase is an ordered list of agents, each with a
prompt, that produces something and gets checked. that is one shape with two
names, kept in two places, and the only honest difference between them was that
one of them could actually run.

so a phase loads as a flow now. the file's words are translated into flow words,
the flow loader validates what comes out, and what you get back is a `FlowSpec`
like any other. a seat is a step, `entry` and `exit` and `produces` are the
three promises, and `gate: user` is a `pause` on the last step. the repo used to
hold two loaders, two validators and two object models for one shape; it holds
one of each now, and this file was the argument for doing it.

that is a change of representation and nothing else. no phase ran before and
none runs now.

## the shape

    lead: lead

    phases:
      - name: research
        agents: [doc-researcher, business-analyst, product-qa]
        produces: a feature doc with requirements and scope boundaries in it

      - name: planning
        agents:
          - {agent: code-reviewer, personality: refactor-advocate}
          - {agent: code-reviewer, personality: minimalist}
          - architect
        produces: one plan, with the two reviewers' conflicts already resolved
        gate: user

- **the lead** runs the whole thing and does not implement. it is not a phase and
  it is not something you launch.
- **an agent** is one launch of one named prompt. the same agent can appear twice
  in a phase with a different `personality`, which is how two reviewers argue from
  fixed positions instead of one reviewer trying to hold both.
- **`gate: user`** is where it parks. there are two, deliberately: after planning
  and before delivery. everything between them runs without asking.
- **`loop`** caps how many times a phase repeats before it is a person's problem.
- **`sequential`** is for phases whose agents cannot run at once, because they
  share something outside the process.
- **the agent's own file** carries the rest of what a seat is, in frontmatter:
  `model:` is the tier it wants and `tools:` is what it may touch. both are
  read now, and both become step keys. what is still only in that file is
  `personality`, and the `name:` line saying which seat the file is for.

## how much alike, exactly

"a phase is a flow" is a claim i made by reading two files and noticing they
looked the same. this counts it instead:

    python run.py vocab

it lines the two vocabularies up: every key a flow file may use against every
key the workflow file actually uses, which of them are one idea under two
names, which exist on one side only, and which words are spelled the same on
both sides while meaning different things. then the same questions asked of the
files in this repo - how many units, how many named jobs, how many conditions
are written down, and how many of those anything checks.

two things fell out of it that i had not seen by reading.

**the vocabularies are not asked the same way.** the flow loader publishes the
keys it accepts and complains about the rest, so its vocabulary is a fact about
the code. the workflow loader takes whatever is in the file and says nothing,
so the only way to find out what a phase may say is to go and read one. that is
why `phase_vocabulary()` reads the file and `flow_vocabulary()` does not.

it reads two files now. a seat is one line in `workflow.yaml` and everything
about the seat is in the agent's own frontmatter, which nothing here had ever
parsed - so the vocabulary was answering for half the phase side and did not
say so. opening the second file is what the tier needed and it is where the two
words that grew the phase-only column came from.

**`gate` means two opposite things.** on a step it is a program that fails the
run. on a phase it is a person the run waits for. one of them is a check and
the other is a stop, and they are the same five letters in two files i keep
open at once.

the second of those is the one word that moved first. a step can say
`pause: user`, and the runner stops there, writes a handoff and waits to be
told to carry on - `docs/journal.md` has the shape of it. it is spelled
`pause` and not `gate` because `gate` on a step was already taken by the
program, and one file using one word for two opposite things is enough.

the counts are the argument, not the prose:

    loaded as                   7 flow specs      8 flow specs, translated
    conditions in prose         19 invariants     16 entry and exit lines
    of those, something checks  3 of 19           none of 16
    declares a tool grant       0 of 20 steps     20 of 20 seats
    something executes it       20 of 20 steps    0 of 8 phases

the grant row is the only one where the two sides are opposites, and it is the
one to watch. every seat says what it may touch and no step in the repo does,
which is what a word looks like the day after it crossed and before anything
started using it on the other side.

the bottom two rows did not move when the merge landed, and that is the best
evidence it was a merge and not a rewrite. an exit line is an invariant now and
still nothing checks it: the checker knows three shapes and no exit line in the
file is any of them, so one vocabulary bought a shared word and not a check.

`unmapped()` is the part that keeps it honest. every key on both sides has to
be placed in the map, a test fails while one is not, so a key added to either
file stays visible until someone says what the other side calls it. the map is
now held against the loader's own translation table by a second test, so it
cannot quietly describe a merge that is not the one happening.

## which side gave

9 ideas have a name on both sides, 19 exist only as a flow key and 7 only as a
phase key. i expected the phase file to give, on the grounds that its words
were words and the flow side's were machinery, and a word moves in an
afternoon. the words that could move have: `name` and `agents` are pairs now
because a phase is a flow spec, and `pause` went the same way earlier.

**`model` is the eighth pair and it is the one that cost something.** every
agent file has declared a tier since the day they arrived - `model: high` on
line 3 - and nothing read it, so it was a comment with a colon in it. a step
has the word now: the checker takes it, refuses anything that is not `high`,
`mid` or `low`, and a provider resolves it to whichever id the environment
holds for that tier. that is the first phase word to become a flow key
something READS. everything else the merge had carried was already a word the
runner had.

**`tools` is the ninth, off the same line of the same files, and it is the one
that had to be sized honestly.** the architect grants itself `[read, grep]` and
then argues it in prose a few lines down - "you are deliberately given no shell
and no write access" - so the boundary was written twice in one file and read
neither time. it is a step key now: the checker refuses a tool it has no name
for, the grant goes into the step's prompt, and what comes back is read against
it by `guardrails/boundary.py`.

what it is NOT is enforcement, and that was the whole risk in carrying the
word. nothing in the runner is in the path of a tool call - a provider takes a
prompt and returns text - so there is no call to intercept and a finding is a
record, not a stop. `docs/guardrails.md` has the exact shape. a phase word that
crossed as something narrower than it sounds is still worth more than one that
crossed as a key nothing reads; the trap is letting the doc round it up.

what is left will not go that way. seven things the file says have no flow word
at all:

- **several different roles at the same time.** `fanout` is one role in many
  copies, which is the other kind of many. `sequential` is the only mark the
  phase file makes, and it marks the exception.
- **`lead`**, the prompt that runs the whole thing and does not implement. a
  flow's lead is the runner, which is code.
- **`personality`**, the same prompt twice from a fixed position. the second
  prompt file has a home now that a role's words are a library, but a step
  still names a role and nothing names a stance.
- **`loop`**, the number of times round. a flow names who a verdict sends the
  work back to, and the engine hands the router the number of trips itself.
- **an ordered list of flows, and its name.** a flow spec says nothing about
  what runs after it.
- **`name` in an agent's own frontmatter**, the file saying which role it is
  for. a flow's prompt file has no frontmatter - the role is the file's NAME,
  which is the whole of the flow side's answer, and it is why a step's role is
  derived by slicing `.md` off it.

that last one is new here only in the sense that nothing had opened the file it
lives in. it was always being said - and so was `tools`, which is why the
phase-only column went up to 8 when the agent files were first read and back
down to 7 as soon as one of the two words found a reader.

every one of those would be a new key on the loader the runner actually uses,
read by nothing - which is exactly what `model` and `tools` are NOT, and the
difference is the test for whether a word is worth carrying. that is the flow
side giving, not the phase file, and a runner does not move in an afternoon.
the expectation was wrong in the interesting direction, and the count is what
showed it.

the two of them also bought two checks nobody had asked for, both of them
gaps in the FILES rather than failures of the loader, both counted the way
`uncriteried()` counts a phase with no exit line, and both empty today.
`misnamed()` is the tier's: something is read off the agent file now, so a copy
of one with the old `name:` left in its header answers for the wrong seat.
`ungranted()` is the grant's: a seat with no `tools:` line becomes a step with
no boundary on it, and the check then has nothing to hold the output against.

two of the nine pairs did not survive either. `loop` and `sequential` looked
like pairs while both sides were only being described; a translation has to
pick a word, and for those two there was none to pick.

the file keeps its own words, and it should. its header is a running account of
what was and was not taken out of it on the way over, and rewriting it into
flow vocabulary would throw away the evidence that what came over came over
whole. whether it stays a dialect for good is not settled here.

## what it does not do yet

nothing here enforces anything. it reads `orchestrate/workflow.yaml` and the
agent files beside it and tells you what they say. no phase is executed, no
phase's gate parks anything, no budget is charged, and no entry or exit
criterion is checked.

two things are read for real rather than printed, and it is worth keeping the
line between them sharp. a seat's `model:` becomes a step key that the checker
validates and a provider acts on. a seat's `tools:` becomes a step key that the
checker validates, that the runner puts into the step's prompt, and that
`guardrails/boundary.py` holds the answer against - which is a check on the
output and not a fence around the call, because nothing in this repo is in the
path of a tool call the model makes.

what neither of them does is run the phase the step belongs to. the tier and
the grant crossed; the phase still has nothing to execute it.

the parking is worth being exact about, because it is the one thing that has
crossed. a run parks now: a step says `pause` and the runner reads it. a
phase's `gate: user` becomes that same word on the last step of the spec the
phase loads as - and it still parks nothing, because nothing hands that spec to
the runner. the translation is real. the run is not.

what is missing is not a shape any more. a phase is a flow spec; what it has
not got is anything that runs it. that is a smaller gap than the one this
section used to describe, and a different kind of one - it was a modelling
problem and it is a wiring problem now. it is still not done.

the prompts had the same problem in a different form and that half is done. the
names were out of them already - no product, no client, no hosts - and the
opinions are out now too: the endpoint layer, the mapper, the real database
behind the integration tests, the coverage number i picked for one codebase.

what is left is smaller and stranger. every role is still told which files to
read before it starts, and two of the three do not exist in this repo at all. a
role should say what it needs to have read, not where that happened to live in
the codebase i wrote it for.

## the other half of that sentence

`orchestrate/project.example.yml` is where the second half goes. one file per
project, beside the workflow: the stack, which docs a role has to have read,
the coverage numbers, the forbidden patterns, the commands that are gates, and
the tier and grant each role gets. copy it to `project.yml` and answer it for
your own repo.

the split is the point. agentweft ships the shapes - role, phase, gate, grant,
tier - and a shape that names a folder is not a shape. everything specific is
specific to one codebase, so it belongs in that codebase's file, which is also
what makes the shapes reusable at all.

the file argues with itself on purpose, and the section names are the argument:

- `standards:` is PROSE. it reaches a prompt, so it can be read, agreed with,
  and then not done, and nothing here will know.
- `coverage:` is NUMBERS. one somebody picked while looking at one codebase,
  which is exactly why it is in this file rather than in a role.
- `gates:` are PROGRAMS. argv, an exit code, nothing to agree with.

anything under `standards:` can be ignored. anything under `gates:` cannot.

what it does NOT do yet is the same answer as everything else on this page:
nothing reads it. no role takes its pre-work from it, no gate takes its numbers
from it, and no reject rule is checked against anything. what exists is the
format and a loader that refuses a word it has no name for, the way `flow.yaml`
has for months - `project.yml: roles: architect: no such tool shel. there is:
read, grep, write, edit, shell, browser`. a tier is `spec.TIERS` and a grant is
`spec.GRANTS`, borrowed rather than restated, because a second list of what
`high` means is how one repo grows two answers.

`run.py vocab` carries the count it exists to bring down. 17 of the 20 seats
name a path in their own prose; 0 of the 20 steps on the flow side do, because
a flow's prompt names nothing outside itself. that row is the gap, and it does
not move until something reads the file.
