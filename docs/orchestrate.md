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

publishing them separately would have meant maintaining the same idea twice
while calling it two ideas. folding it in means one of them has to give. working
out which one is the part worth doing in public.

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

the second of those is the one word that has since moved. a step can now say
`pause: user`, and the runner stops there, writes a handoff and waits to be
told to carry on - `docs/journal.md` has the shape of it. it is spelled
`pause` and not `gate` because `gate` on a step was already taken by the
program, and one file using one word for two opposite things is enough.

the counts are the argument, not the prose:

    conditions in prose         19 invariants     16 entry and exit lines
    of those, something checks  3 of 19           none of 16
    something executes it       20 of 20 steps    0 of 8 phases

`unmapped()` is the part that keeps it honest. every key on both sides has to
be placed in the map, a test fails while one is not, so a key added to either
file stays visible until someone says what the other side calls it.

which side gives: 9 ideas have a name on both sides, 17 exist only as a flow
key and 4 only as a phase key, and nearly everything flow-only is machinery
while nearly everything phase-only is a word. a word moves in an afternoon and
a runner does not, so i expect the phase file to be the one that gives.

that is still an expectation, but it now has one data point under it. the stop
that waits for a person was a phase-only word when this was first counted; it
is a pair now, because the flow side grew `pause` and the runner does the
parking. it took an afternoon, which is what the expectation said it would.
one word is not a decision, and both files still say what they said.

## what it does not do yet

nothing here enforces anything. it reads `orchestrate/workflow.yaml` and tells
you what it says. no phase is executed, no phase's gate parks anything, no
budget is charged, and no entry or exit criterion is checked.

the parking is worth being exact about, because it is the one thing that has
crossed. a run parks now, and nothing in this file makes it happen: a step says
`pause` and the runner reads it. `gate: user` in `workflow.yaml` is still prose
that nothing reads. what moved was the idea, not the file.

the runner already does all of that, for a flow. it does none of it for a phase,
because a phase is not a flow yet - it is a list in a file that happens to have
the same shape as one. closing that gap is the work, and it is not done.

the prompts had the same problem in a different form and that half is done. the
names were out of them already - no product, no client, no hosts - and the
opinions are out now too: the endpoint layer, the mapper, the real database
behind the integration tests, the coverage number i picked for one codebase.

what is left is smaller and stranger. every role is still told which files to
read before it starts, and two of the three do not exist in this repo at all. a
role should say what it needs to have read, not where that happened to live in
the codebase i wrote it for.
