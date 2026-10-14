# Taking groundwork to a new domain in a day

This is the playbook. It assumes you have a customer, a system they care about, and
about a day. It is written from doing this twice in this repo, once for pipeline
operations and once for grounded compliance answering, and the two came out looking
remarkably similar despite having nothing in common.

The one line version: find the decision, wrap the data that decision needs, write the
eval cases before the agent, then build until they pass.

## Hour 0 to 2: scoping

You are not looking for "a use case". You are looking for one decision that a person
makes repeatedly, with a known-good answer, where the cost of getting it wrong is
visible. If you cannot name the decision, you cannot evaluate it, and an agent you
cannot evaluate is a demo.

Questions worth asking, roughly in this order:

**What does someone do at 9am?** Not what the system does. What the human does. In the
`adf_ops` domain the answer was: open a dashboard, see six red pipelines, and start
working out which one actually broke. That sentence is the whole product.

**How do they know when they are done?** This is the stop condition, and it goes
straight into the skill. For triage it was "you have named one root cause and can point
at the specific activity and error code". For compliance it was "every claim has a
citation, or you have said the corpus does not cover it".

**What does a wrong answer look like, specifically?** Push until you get a story, not
a category. "Hallucination" is useless. "It told a customer they needed to register
with the data commissioner when they do not handle personal data" is an eval case. The
best scoping question in this list.

**What do they look at, in what order?** This is your tool list. If they check the run
history, then the activity breakdown, then the error payload, then you need three tools
in that shape, and your skill tells the agent to walk them in that order.

**What would they never let an agent do?** This gives you the read/write boundary. Both
servers here are read only, and on a first engagement that is usually right. Read only
is a much easier conversation with a security reviewer, and the hard part of the
problem (knowing what to do) is upstream of the writing anyway.

**What is the system of record, and can I get a copy of its shape?** Not its data. Its
shape. You can build and evaluate the entire thing against synthetic fixtures and swap
in the real client at the end, which is what both servers here do. This also gets you
past the data access conversation, which is usually the longest pole.

Red flags that the scope is wrong: nobody can tell you what a wrong answer looks like;
the decision happens twice a year; the answer depends on context that only lives in
someone's head and nowhere in any system; or the real problem is that the data is
wrong, in which case an agent will confidently report wrong data faster than a human
would.

## Hour 2 to 4: choose the tool boundary

The tool boundary is the highest leverage design decision in the whole engagement, and
the one most people rush.

**Tools should be nouns and verbs the customer already uses.** `get_run_activities` is
a good tool because an operations engineer already thinks in runs and activities.
`query_database` is a bad tool, because now the agent has to know your schema, and when
it gets the schema wrong the failure is silent and looks like an answer.

**One tool per question someone actually asks.** `summarize_failures` exists because
"what broke last night" is a question people ask. It is a trivial aggregation over
`list_pipeline_runs` and you could argue the agent should do it itself. You would be
wrong: making it a tool means you can assert that the agent asked that question, and it
saves three round trips.

**Add a tool for the step people forget.** `find_upstream_dependencies` is the whole
reason the `adf_ops` suite is interesting. Without it, the agent can see six failures
and has no way to relate them, so it does what an inexperienced engineer does and
reports the first one. The tool does not make the agent smarter. It makes the right
answer reachable. Every domain has one of these, and finding it is most of the value
you add.

**Make the tool return what it knows, and make its description say what it does not
know.** The description is the only documentation the model gets. Ours say things like
"a status of Skipped means an upstream activity did not succeed, so a skipped activity
is never itself the problem". That single sentence removes a whole class of wrong
answer, and it costs nothing. On a real engagement, tool descriptions are where you put
the knowledge that currently lives in the head of the person who has been there
longest.

**Errors are part of the interface.** A tool that raises on a bad argument should come
back as a readable message that names the valid options, not a stack trace. Our
`get_document` error lists every real document id, so an agent that invents
`DOC-TAX-03` is told the real ids and can recover in one turn. Test this. There is an
eval case in each suite that does nothing except make a bad call and check the agent
recovered.

**Granularity test:** if a tool's output routinely needs to be filtered by the model
before it is useful, the filter should have been an argument. If two tools are always
called together, they are one tool.

## Hour 4 to 6: write ten eval cases, before the agent

This is the part people skip and it is the part that works.

Write the cases as plain sentences first, on paper, with the customer in the room if you
can get them. You are asking: what would make you trust this? Then turn each sentence
into a case. Ten is the right number for day one. Not three, which is a demo, and not
fifty, which you cannot maintain before you know what matters.

A balanced first ten looks roughly like:

- **Three happy paths.** The obvious question, asked the obvious way. If these do not
  pass, nothing else matters.
- **Two where the obvious answer is wrong.** This is the heart of it. In `adf_ops`,
  `root_cause_cascade` asks what broke on a night when six things broke, and the right
  answer is one upstream throttling error. `skipped_is_not_cause` checks the agent does
  not blame an activity that never ran.
- **Two negative cases.** Things the agent must not say. `separate_incidents` checks
  that a genuinely unrelated failure does not get folded into the cascade story.
  `out_of_scope_refusal` checks the agent says "the corpus does not cover this" instead
  of answering from general knowledge. Negative cases are where you encode the
  customer's actual fear.
- **One grounding case.** Every claim traceable. `cites_source` does this
  deterministically and cheaply, and it is worth building an equivalent for whatever
  "source" means in your domain, even if it is a row id.
- **One recovery case.** A tool fails or an argument is wrong, and the agent must
  notice and correct, not give up and not invent. If your agent cannot do this it will
  not survive a week in production, because real systems time out.
- **One efficiency case.** A budget on turns or tool calls. Agents that work by calling
  everything are expensive and slow, and the budget is how you notice when a prompt
  change made that worse.

Assert on tools, not just text, wherever you can. `contains: "RestSourceCallFailed"`
tells you the right string appeared. `tool_called: find_upstream_dependencies` tells you
the agent actually looked. The second one is what distinguishes a correct answer from a
lucky one, and it is the check that keeps working after you change the prompt.

Write the expected behaviour down even for cases you expect to fail at first. A failing
case on day one is a roadmap. In this repo the first run of the `ke_compliance` suite
failed three of five cases, and two of those failures were genuine citation errors in
the hand written transcripts, not harness bugs. That is the harness doing its job
before a single real API call was made.

## Hour 6 to 8: write the skill, then iterate

Only now write the skill, because now you know what good looks like.

A skill is not a personality. It is the procedure a competent new hire would be handed
on their first day. Ours have the same four parts, and yours probably should too:

1. **What you are being asked to do**, in one or two sentences.
2. **The procedure**, as ordered steps that name specific tools. "Call
   `find_upstream_dependencies` before you conclude anything about cause" is a step. "Be
   thorough" is not.
3. **Stop conditions.** When to answer, and when to stop looking. Agents without a stop
   condition either halt too early or spend twenty turns being diligent about nothing.
4. **Failure handling.** What to do when a tool errors, what to do when a search returns
   nothing, and what to say when the answer is not available. Spell out the refusal. An
   agent that has been told exactly how to say "I do not know" is much more likely to
   say it.

Then the loop: run the suite, read the failures, change one thing, run again. Change one
thing at a time or you will not know which change helped. Most of your early fixes will
be tool descriptions rather than the skill, which surprises people. The model is usually
not confused about what to do. It is confused about what the data means.

## Deciding when it is good enough to hand over

Not "when the suite is green". A green suite means you wrote cases it passes.

The questions worth answering honestly:

**Does it pass cases it did not pass the first time?** If every case passed on the first
run, your cases are too easy and you have measured nothing.

**Can the customer add a case without you?** This is the real handover test, and it is
why suites here are YAML and the scorers are a registry. If adding a case requires
writing Python, you have not handed anything over, you have created a dependency on
yourself.

**Does it fail in a way that is obvious?** Run the suite with a deliberately broken tool
and read the output as if you were the customer. If the failure is a stack trace, fix
the reporting before you hand over.

**Does it know what it does not know?** Ask it three questions outside its scope. If it
answers all three, it is not ready, regardless of the suite.

**What is the cost of the worst wrong answer that passes the suite?** Write that
sentence down and put it in the handover document. Every agent has one. The customer
should hear it from you first.

**Is there a path to running this live?** Replay in CI is necessary but not sufficient.
There should be a scheduled live run, a place its results go, and a named person who
looks at them. Without that, the suite rots in a fortnight.

A reasonable bar for a first handover: ten to twenty cases, green under replay on every
commit, a live run on a schedule, a written list of known failure modes, and a customer
who has added at least one case themselves. That is enough to be useful and honest about
its limits, which is better than a system that looks more finished than it is.

## What transfers and what does not

Building the second domain in this repo took a fraction of the time of the first, and
the split was instructive.

Transferred unchanged: the agent loop, the MCP client, every scorer, the runner, the
reporting, the recording format, the CLI, and the entire shape of the suite YAML. None
of the core knows that pipelines or compliance documents exist.

Did not transfer, and should not have: the tool boundary, the fixtures, the skill, and
the cases. Those are the domain. Roughly, expect a day of real thinking on the tools and
the cases, and an afternoon of plumbing.

The failure modes did not transfer either, which is the most useful finding here. The
pipeline agent fails by being too credulous about the first error it sees. The
compliance agent fails by being too confident when the corpus is silent. Same core, same
model, same harness, completely different wrong answers. You cannot carry over your
intuitions about how it will break. You have to go and find out, which is what the first
ten cases are for.
