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

## what it does not do yet

nothing here enforces anything. it reads `orchestrate/workflow.yaml` and tells
you what it says. no phase is executed, no gate parks a run, no budget is
charged, and no entry or exit criterion is checked.

the runner already does all of that, for a flow. it does none of it for a phase,
because a phase is not a flow yet - it is a list in a file that happens to have
the same shape as one. closing that gap is the work, and it is not done.

the prompts have the same problem in a different form. the names are out of them
- no product, no client, no hosts - but the opinions are not. they still assume
an endpoint layer, a mapper, a real database behind the integration tests, and a
coverage number i picked for one codebase. a role should be a shape, not one
project's habits wearing a job title.
