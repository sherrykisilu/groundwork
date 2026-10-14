# Decisions and what they cost

Six decisions that were genuinely contested, in the sense that the opposite choice is
defensible and is what most comparable projects do. For each: what was chosen, what was
rejected, what the choice actually costs, and what evidence would make me reverse it.

A tradeoff with no stated cost is not a tradeoff, so the cost section is the one worth
reading.

---

## 1. Assert on which tools were called, not on which words appeared

**Chosen.** The scorer registry has ten scorers, and the two the README says earn their
keep are behavioural: `tool_called` asserts a specific tool ran, optionally with
matching arguments, and `cites_source` fails any `DOC-XXX-01#S2` shaped citation whose
exact string never appeared in a tool result
(`src/groundwork/core/evals/scorers.py`). `tool_sequence` asserts order as a
subsequence. Every case in both suites carries at least one behavioural scorer, and
`tests/test_suites.py` enforces that as a repo wide invariant.

**Rejected.** Text assertions as the primary signal, which is what most eval setups
do, or an LLM judge as the primary signal, which is the current default in a lot of
tooling. Both exist here. Both are deliberately secondary.

**Why.** The failure this repo is built around is a fluent answer that is wrong.
`contains: "RestSourceCallFailed"` tells you the right string appeared, which a model
can produce from the prompt alone. `tool_called: find_upstream_dependencies` tells you
the agent actually went and looked. The playbook puts it in one line: the second check
is what distinguishes a correct answer from a lucky one, and it is the check that keeps
working after you change the prompt.

**What it costs.** Three things, none of them small.

- The suite is now coupled to the tool boundary. Rename `summarize_failures` or split
  it in two and every case asserting on it breaks, even though the agent's behaviour
  did not change. Text scorers do not have this problem.
- `tool_called` proves the agent looked, not that it understood what it saw. An agent
  that calls the right three tools and then draws the wrong conclusion passes the
  behavioural half of the case and has to be caught by the text scorers you just
  demoted.
- Argument matching is deliberately loose. `_argument_matches` compares strings by
  case insensitive substring, so `pipeline: publish_sales_dashboard` is satisfied by
  any argument containing that text. The docstring defends this, and it is right that
  casing should not fail a case, but it means a genuinely wrong argument that happens
  to contain the expected substring passes.

**What would reverse it.** If tool boundaries churned faster than agent behaviour, so
that most suite failures were renames rather than regressions, the coupling would be
costing more than it buys. Or, more seriously, a case that goes green while the final
answer is wrong: that is the behavioural scorers flattering the agent, and the fix is
to strengthen the output side rather than the action side.

---

## 2. Build tools for the steps a person forgets, even when the model could do it itself

**Chosen.** `find_upstream_dependencies` and `summarize_failures` are tools, not
things the agent assembles out of smaller calls. The playbook is explicit that
`summarize_failures` is a trivial aggregation over `list_pipeline_runs` and that you
could argue the agent should do it itself, and then argues the other way: making it a
tool means you can assert the agent asked that question, and it saves three round
trips. `find_upstream_dependencies` is stronger still. The commit adding the server
says it is the tool that makes the true root cause reachable.

**Rejected.** A thin faithful mirror of the underlying API, with all composition left
to the model. That is the purist position and it has a real argument behind it: every
convenience tool you add is a judgement you have baked into the interface.

**Why.** Without the dependency tool, the agent can see six failures and has no way to
relate them, so it does what an inexperienced engineer does and reports the first one.
The tool does not make the model smarter, it makes the right answer reachable.

**What it costs.** This is the decision I am least comfortable defending, because it
has a circularity in it. The eval suite asserts that the agent called
`find_upstream_dependencies`, and `find_upstream_dependencies` exists because the case
is unsolvable without it. I built the tool and then wrote the case that checks the
tool was used. That is not cheating, since a real engineer genuinely does need
dependency information and the tool is a fair model of information that exists in the
system, but it does mean the suite measures adherence to my procedure as much as it
measures correctness. A second cost: each composed tool is a place where my judgement
about what matters is now invisible to the model, so when my judgement is wrong the
failure is silent.

**What would reverse it.** An agent that solves the cascade case without the tool, by
composing `get_pipeline` lineage calls itself, would show the composition was
unnecessary at this scale. Or a domain where I cannot name the forgotten step, which
the playbook treats as a scoping red flag rather than a reason to add tools anyway.

---

## 3. Ship a replay provider instead of requiring API keys in CI

**Chosen.** `ReplayProvider` replays recorded model turns from JSON. CI runs both eval
suites under it on 3.11, 3.12 and 3.13 with no secrets block. The important design
detail is that replay covers only the model side: tool calls still execute for real
against the real MCP servers over a real stdio transport, so a broken server, a broken
fixture or a bad tool schema still fails the run.

**Rejected.** Live model calls in CI with a key in repository secrets, which is the
common setup, or mocking the tools as well, which is the lazier version of what was
built.

**Why.** It produces a gate that runs in about a second, costs nothing, is byte for
byte reproducible, and that a customer can run on a laptop on day one. Mocking the
tools too would have been easier and would have tested nothing: the whole point is
that the tool layer is the part that breaks on a real engagement.

**What it costs.** The README states this plainly and it is worth not softening. You
give up live model behaviour entirely. In replay the model has no mind to change, so
the suite cannot catch a prompt edit that makes the agent worse, a model version
change, or any nondeterminism at all. Worse, the cost compounds with how the
recordings were made: they are hand authored rather than captured from live runs,
because there was no API key on the machine where this was built, so the live
Anthropic path is implemented and documented but has never been exercised end to end.
A suite that is green under replay has proven that the servers work and that the
asserted behaviour is internally consistent. It has not proven the agent does this.

**What would reverse it.** It should not be reversed, it should be completed. The
playbook already names the shape: replay on every commit, live on a schedule, with a
named person who reads the results. The trigger for prioritising that work is the
first disagreement between a live run and the replay baseline, and until a live run
has happened at all, the disagreement rate is unknown rather than zero.

---

## 4. Let the judge scorer pass when it cannot run

**Chosen.** With no provider configured, `judge` returns `passed=True` with the reason
"skipped: no judge provider configured" and a `skipped: True` detail
(`scorers.py`). The README calls this a deliberate choice and a real weakness in the
same sentence.

**Rejected.** Failing closed, which would turn every offline run red and defeat the
point of the replay provider. Or reporting the case as skipped rather than passed,
which is the middle option and the one I now think was right.

**Why.** Offline CI has to stay green with no secrets, and that constraint is load
bearing for everything else in the repo.

**What it costs.** It inflates the headline. The sample run in the README prints
`root_cause_cascade  8/8`, and under replay one of those eight is a judge scorer that
did not execute. A reader counting scorers reads more assurance than ran. The repo
mitigates this honestly in prose, in both the README and the scorer's own docstring,
but prose is not the artifact a CI badge shows. This is the one decision here where I
think the documentation is carrying weight the code should carry.

**What would reverse it.** Any suite whose signal depends materially on `judge`, which
is to say any domain where correctness is not expressible as a tool call or a literal
string. The fix is not to fail closed, it is to make a skip visible as a third state
in the report and in the exit code's reasoning, so `8/8` becomes `7/7 with 1 skipped`.
That is a small change and it is a code change, so it belongs on a roadmap rather than
in this document.

---

## 5. Keep the core domain neutral, and pay that cost with only two domains in it

**Chosen.** Everything in `core/` is domain neutral and everything in `servers/` is
one domain. Suites are YAML, scorers are a registry, the runner knows nothing about
pipelines or compliance documents. Adding a domain means adding a server, a skill and
a suite, and changing nothing in the core.

**Rejected.** Writing the first domain concretely and extracting an abstraction once a
third domain demanded one, which is the usual and usually correct advice. Generalising
from two examples is how most bad abstractions are born.

**Why.** The claim the repo is making is that this is a pattern rather than a one off,
and that claim is only credible if two unrelated domains share the core without either
bending it. The second domain is not a feature, it is the evidence. The playbook
records what actually transferred: the loop, the MCP client, every scorer, the runner,
the reporting, the recording format, the CLI and the suite schema. What did not
transfer was the tool boundary, the fixtures, the skill and the cases, which are the
domain.

**What it costs.** Indirection that two domains do not need. A scorer registry with
dispatch by string name, a YAML schema that has to be general enough for cases nobody
has written, and a `ScoringContext` that exists mostly so the judge scorer can reach a
provider. If this repo only ever had `adf_ops` in it, a hundred lines of direct Python
would do the same work and be easier to read. There is also a subtler cost: the core
is now a thing I have to keep neutral, so a feature that would obviously help pipeline
triage cannot go in it.

**What would reverse it.** A third domain that cannot be added without changing the
core. That is the designed falsification test and it has not been run yet. The nearest
thing to a run is the voice branch, which added an interface over an existing domain
with no core change, and that is weaker evidence than a third domain would be because
an interface and a server are not the same shape of addition.

---

## 6. In the voice branch, translate citations into spoken attributions rather than strip them

**Chosen.** On the unmerged `sherrykisilu-microsoft-voice-layer-elevenlabs` branch,
`interfaces/voice/speakable.py` applies four rules. Grounding is checked before
anything is synthesised, by calling the core's own `cites_source` scorer rather than
reimplementing it. An answer with an ungrounded citation is never spoken, and the
listener gets a refusal naming the invented id. A citation is translated rather than
deleted, so `(DOC-DPA-01#S1)` becomes a spoken attribution built from the title the
tools actually returned, and the rewrite is counted back against the written answer so
that dropping an attribution raises rather than returning quieter audio. An answer
citing nothing at all is spoken with an audible warning, because a correct refusal and
an unsupported claim look identical to a deterministic check.

**Rejected.** Stripping citations before synthesis, which is the obvious
implementation and what a wrapper around a text to speech call would do. The branch's
own commit message states why it was rejected: reading `DOC-DPA-01#S1` aloud is
unbearable, so stripping it ships an answer whose grounding is invisible to the only
person receiving it. That is the precise failure the whole project exists to catch,
reintroduced by the interface.

**What it costs.** Three costs, and the branch names all three.

- A spoken attribution is not machine checkable the way an id is. A listener who wants
  to verify a claim needs the written answer, which `SpokenAnswer.written` always
  carries, or `--spell-ids`, which reads the ids out character by character.
- The rewrite is tuned to the bracketed citation style this corpus and skill produce.
  A domain that cites differently needs the pattern widened.
- `to_spoken` raises a `SpeakableError` rather than degrading, so a formatting change
  in the answer turns a soft quality problem into a hard failure. That is the right
  default for a grounding guarantee and it is still a real operational cost: the
  stricter the gate, the more often it fires on something that was not actually a
  grounding problem.

**What would reverse it.** A domain whose sources have no stable readable title, where
there is nothing to translate a citation into. The fallback there is the spelled id,
which is unbearable, so the honest answer in that case may be that voice is the wrong
interface rather than that the gate should be relaxed.

---

## The three I would defend first in a conversation

Decision 1, because it is the one that makes the eval suite mean anything. Everything
else in the repo is downstream of the claim that you assert on actions rather than on
wording.

Decision 3, because the cost is severe, stated in the README without hedging, and
still worth paying. It is the clearest example here of choosing a weaker instrument
that actually gets used over a stronger one that would sit behind a procurement
conversation.

Decision 6, because it is the one where the principle was tested by something that
genuinely threatened it. A grounding guarantee that only survives in text is a
guarantee about the format, not about the system. Catching that in an interface layer,
and paying for it with a stricter failure mode, is the decision I would most want to
be asked about.

*Inference:* the repo documents what each decision is and, in most cases, why. It does
not anywhere enumerate the rejected alternative or the reversal condition in these
words. Decisions 1, 3 and 6 have their rationale stated almost verbatim in the README,
the playbook or the branch commit message. The costs in decisions 2 and 4, specifically
the circularity between a composed tool and the case that asserts it, and the claim
that a skipped judge inflates the printed scorer count, are my reading rather than the
repo's, and they are the two I would most want confirmed before this is published.
