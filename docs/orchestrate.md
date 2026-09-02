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
    something executes it       20 of 20 steps    0 of 8 phases

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

7 ideas have a name on both sides, 19 exist only as a flow key and 6 only as a
phase key. i expected the phase file to give, on the grounds that its words
were words and the flow side's were machinery, and a word moves in an
afternoon. the words that could move have: `name` and `agents` are pairs now
because a phase is a flow spec, and `pause` went the same way earlier.

what is left will not go that way. five things the file says have no flow word
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

every one of those would be a new key on the loader the runner actually uses,
read by nothing. that is the flow side giving, not the phase file, and a runner
does not move in an afternoon. the expectation was wrong in the interesting
direction, and the count is what showed it.

two of the nine pairs did not survive either. `loop` and `sequential` looked
like pairs while both sides were only being described; a translation has to
pick a word, and for those two there was none to pick.

the file keeps its own words, and it should. its header is a running account of
what was and was not taken out of it on the way over, and rewriting it into
flow vocabulary would throw away the evidence that what came over came over
whole. whether it stays a dialect for good is not settled here.

## what it does not do yet

nothing here enforces anything. it reads `orchestrate/workflow.yaml` and tells
you what it says. no phase is executed, no phase's gate parks anything, no
budget is charged, and no entry or exit criterion is checked.

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
