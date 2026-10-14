# Who this is for, and what it fixes

I did not start from a persona. I started from what the repo spends effort on, because
where a codebase pays a cost is the most honest statement of who it is for. Four of
those costs point at the same person.

## What the repo pays for, and what each cost implies

**It ships a `ReplayProvider` before it ships anything that makes money.** Replaying
recorded model turns from JSON is real work, and the only thing it buys is a suite that
runs with no API key, in about a second, identically every time
(`src/groundwork/core/agent/providers.py`). You do not build that for someone who has a
key. You build it for someone whose team has not finished the procurement conversation,
or whose CI runner is not allowed to hold a secret, or who needs the eval to run on a
reviewer's laptop during a meeting.

**CI runs with no secrets at all.** `.github/workflows/ci.yml` installs, lints, tests
and runs both eval suites under replay, on three Python versions, with no
`secrets` block anywhere. That is a deliberate constraint, not an oversight: the commit
adding CI says so in its message. The implication is that the gate has to work in
someone else's repo, on someone else's org policy, without a negotiation.

**Both domains are modelled on public shapes with synthetic data.** `adf_ops` follows
the documented public Azure Data Factory REST API shape, and every pipeline, run,
error and timestamp in it is generated in `fixtures.py`. The `ke_compliance` corpus
reproduces no statutory text and carries a disclaimer in every tool result
(`servers/ke_compliance/corpus.py`). The README is explicit that nothing derives from
my employer's work. The product consequence matters more than the legal one: you can
build and evaluate the entire thing before anyone grants you access to production
data, and `docs/ENGAGEMENT.md` says exactly that, calling data access "usually the
longest pole".

**Both servers are read only.** Seven tools in `adf_ops`, all queries. The playbook
gives the reason: read only is a much easier conversation with a security reviewer,
and the hard part of the problem, knowing what to do, sits upstream of doing it.

Put those together and the user is not "an AI engineer". It is someone who has to
convince a second party. The replay provider, the secretless CI, the synthetic
fixtures and the read only boundary are all the same move: remove every reason
somebody else can say no before you have shown them anything.

## The problem, stated the way the repo states it

The README opens with it. Most "can an agent do this job?" questions do not fail on the
model. They fail on three things around it: the system has no clean interface, nobody
wrote down the procedure a good engineer follows, and there is no way to tell whether
the agent was right for the right reason or right by accident.

The third one is the expensive one, and it is the one `groundwork` is actually built
around. An agent that produces a fluent wrong answer is worse than one that fails
loudly, because somebody acts on it. `adf_ops` encodes that precisely: on the night in
the fixture, the first error you read is a missing SQL table, and the real cause is an
HTTP 429 three pipelines upstream. An agent that answers from the first error sends the
wrong team to the wrong system. The suite exists to fail that answer even when it reads
well.

## The job, stated as a job

Not as a framework label. The job is: **I have to tell someone whether an agent can be
trusted with this task, and I need an answer that survives them pushing back on it.**

That phrasing does work, because it explains the structure of the repo rather than
decorating it:

- "Tell someone" is why the output is a repo they run themselves, not a demo I drive.
  `docs/ENGAGEMENT.md` makes the handover test explicit: can the customer add a case
  without you. That is why suites are YAML and scorers are a registry rather than
  Python functions a customer would have to write.
- "Can be trusted" is why the headline scorers are `tool_called` and `cites_source`
  rather than text matching. Trust is about the action taken, not the prose produced.
- "Survives pushback" is why the whole suite runs offline and deterministically. A
  result you cannot reproduce in front of the person questioning it is not evidence.

## Who it is not for

It is not for someone running an agent in production. There is no auth, no rate
limiting, no multi-tenancy, and the README says all three would be needed. It is not
for someone with a large corpus: retrieval is BM25 over six documents, which is the
right call at that size and the wrong one at six hundred. And it is not a framework
competing with an agent SDK. The core is roughly 1,450 lines of domain neutral code,
including docstrings, and its job is to make a claim checkable rather than to be the
thing you build on.

*Inference:* the repo never names a user in those words. The four costs above are read
from the code and the commit messages. The reading I am least certain about is that
the secretless CI is aimed at someone else's org policy rather than simply at my own
convenience while building without a key, and both could be true at once.
