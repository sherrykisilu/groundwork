# How success is measured

There are no users, so there are no usage numbers. Everything below is something the
repo can actually produce, or something it cannot, said as such.

## The instrument

The eval suite is the measurement instrument. One run of
`groundwork run-eval evals/adf_ops.yaml --provider replay` produces, per case:

- a pass or fail, and the count of scorers that passed
- a reason string per scorer, written to be actionable rather than a verdict. The
  design note in `scorers.py` is explicit about why: when a suite goes red at 6pm on a
  customer site, "failed" is useless and "expected `find_upstream_dependencies`, agent
  called `get_activity_error` twice then stopped" tells you what to do next
- the number of tool calls and model turns, which are both separately assertable as
  budgets through `max_tool_calls` and `max_turns`
- wall clock milliseconds per case
- the number of tool errors, with a per case allowance for the cases that provoke one
  deliberately
- for `cites_source`, the grounded and ungrounded citations by id

`run-eval` exits non zero on failure, which is the only thing CI reads. Results can be
written as markdown or JSON with `--report` and `--json`.

There is a second instrument that is easy to miss. `tests/test_suites.py` asserts repo
wide invariants over the suites themselves: every case names a registered scorer, every
case carries at least one behavioural scorer, every case names an existing skill and an
existing recording, and no recording is orphaned. That is a measurement of whether the
suite is still a suite, and it is what stops the cases decaying into text assertions
over time.

## What it genuinely measures

**Whether the agent took the right action.** `tool_called` and `tool_sequence` assert
the agent looked before it concluded. On an operational task this is the thing that
matters, because an answer produced without looking is right by coincidence.

**Whether every claim traces to something a tool returned.** `cites_source` pulls each
citation out of the answer and fails unless that exact string appeared in a tool
result. It is deterministic, costs nothing, and it has caught something real: during
authoring it found two ungrounded citations in the hand written recordings, which is
recorded in the commit that added the suites and repeated in the README. That is the
strongest claim on this page, because it is the only measurement in the repo with a
documented catch behind it.

**Whether the servers and fixtures still work.** Because replay covers only the model
side, tool calls execute for real against the real MCP servers over a real stdio
transport. A broken server, a broken fixture or a bad tool schema fails the run.

**Whether the agent recovers.** Each suite has one case that makes a bad call on
purpose, `tool_error_recovery` and `citation_error_recovery`, and checks that the agent
read the error and carried on. `tests/test_loop.py` covers the same property one layer
down, asserting the error text reaches the model rather than ending the run.

**Whether it stays within budget.** Turn and tool call limits are real assertions in
both suites, not decoration. The playbook's reason for them is that a budget is how
you notice when a prompt change made the agent more expensive.

**Whether it holds across Python versions.** CI runs the whole thing on 3.11, 3.12 and
3.13, with no secrets.

## What it cannot measure, and why

**Live model behaviour.** Under replay the model is a recording. The suite cannot
catch a prompt edit that makes the agent worse, a model version change, or any
nondeterminism. This is the largest limitation and the README states it without
hedging.

**Whether the agent actually does this.** The recordings are hand authored rather than
captured live. So a green suite proves the servers work and that the asserted behaviour
is internally consistent. It does not prove a model produces that behaviour, and it
cannot until the live path has been run at least once.

**How much assurance a scorer count represents.** When `judge` cannot run it returns a
pass, so a printed `8/8` can include a scorer that did not execute. The number is
truthful about how many scorers were satisfied and misleading about how many ran.

**Whether an answer is right beyond what was asserted.** A case checks the strings and
tools I thought to name. The playbook makes the point sharply: a green suite means you
wrote cases it passes. Its proposed counter test is whether the suite contains cases it
did not pass the first time, and if everything passed on the first run the cases are
too easy and nothing has been measured.

**Cost and latency of real use.** The milliseconds in the report are replay latency.
Nothing in the repo records tokens, dollars, or how long a live run takes. The voice
branch is the only place that discusses cost at all, in order of magnitude terms, and
even there it is pricing arithmetic rather than a measurement.

**Corpus coverage.** `out_of_scope_refusal` checks that one specific uncovered
question produces a refusal. Nothing measures what fraction of plausible questions the
six document corpus can answer, so the refusal behaviour is tested at one point rather
than characterised.

**Anything about people.** No adoption, no retention, no satisfaction, no time saved.
The repo has no deployment, no telemetry and no users, so any such number would be
invented.

## What I would instrument, in the order I would add it

Each of these is currently absent, and each produces a number the repo could actually
report.

**Replay versus live disagreement rate.** Run both suites live on a schedule and
record, per case, whether the live verdict matches the replay verdict. This is the
single most informative missing number, because it quantifies exactly how much the
offline gate is worth. A low rate means replay is a good proxy. A high rate means the
offline suite is a server test wearing an agent test's clothes.

**Cost and latency per case on live runs.** Tokens in, tokens out, dollars, and wall
clock. The budget scorers already assert on tool calls and turns, which are proxies
for cost, and proxies stop being necessary once the real figure is recorded.

**First run failure rate for new cases.** When a case is added, record whether it
passed the first time it was run. The playbook already treats this as the test of
whether a suite measures anything, so it is worth counting rather than remembering.

**Cases contributed by someone other than the author.** The playbook names the real
handover test: can the customer add a case without you. Counting cases added by
someone else, and how many needed help, turns that from a claim about the YAML format
into an observation.

**Scorer value, counted by catches.** Per scorer, how many times it was the one that
failed a case that would otherwise have passed. Ten scorers exist and the README
asserts two earn their keep, which is currently a judgement. This number would settle
it, and it would also tell you which scorers to delete.

None of these need a deployment. All five need the live path to run once, which is why
that is first on the sequencing argument in [not-built.md](not-built.md).

*Inference:* the lists of what the suite measures and cannot measure are read from the
code and the suite YAML, and the limitations are ones the repo states. The five
instruments above are mine, except the two drawn from the playbook, which are its
handover questions turned into counters. The claim that the replay versus live
disagreement rate is the single most informative missing number is my judgement.
