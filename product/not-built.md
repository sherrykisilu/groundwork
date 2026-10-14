# What was deliberately not built

Everything here is a cut I can point at in the repo. Each one names the reason given at
the time and, where the reason is weaker than it sounds, says so.

## In the core and the servers

**Write tools.** Both MCP servers are read only. `adf_ops` exposes seven tools and all
seven are queries; its server description says "read only operations tooling" in the
first line. The reason is in `docs/ENGAGEMENT.md`, under the scoping question "what
would they never let an agent do": read only is a much easier conversation with a
security reviewer, and the hard part of the problem, knowing what to do, is upstream of
doing it. The README adds the product reason: an agent that writes needs an approval
story, and that is a different project. This is the largest cut in the repo and the one
most likely to be challenged, because a triage agent that cannot rerun a pipeline
leaves the last step to a human. That is the intended shape for a first engagement, not
a limitation I would defend forever.

**A vector index.** Retrieval in `ke_compliance` is BM25 written in plain Python. The
README gives the reason as size: the corpus is six documents, not six hundred, so BM25
is the right call and a vector index would be overkill. The second reason is implied by
the rest of the repo and worth making explicit, because it is the stronger one: an
embedding index would need a model, which needs a key, which breaks the no secrets
property that CI and the replay provider exist to protect.

**Auth, rate limiting and multi-tenancy.** None of the three exist, and the README
says real deployments need all three. The cut is honest rather than clever: this is a
demonstration of a delivery pattern, and those three are what you add when it stops
being one.

**A third domain.** Two were built, `adf_ops` and `ke_compliance`, chosen to have
nothing in common. The playbook explains what the second one bought: it proved which
parts of the core transferred and, more usefully, that the failure modes did not. The
pipeline agent fails by being too credulous about the first error it sees. The
compliance agent fails by being too confident when the corpus is silent. Same core,
same harness, different wrong answers.

**More than ten eval cases.** Five per suite. The playbook argues the number directly:
ten is right for day one, not three, which is a demo, and not fifty, which you cannot
maintain before you know what matters. The ten are allocated on purpose across happy
paths, cases where the obvious answer is wrong, negative cases, grounding, recovery and
an efficiency budget, and both suites follow that allocation.

**Real statutory text.** The `ke_compliance` corpus is modelled on the general shape of
small business obligations and reproduces no actual law. Deadlines, thresholds and
document ids are invented, every document carries a disclaimer, the tool descriptions
say so, and the server returns the disclaimer alongside results. This is a cut, not an
oversight: a retrieval demo that quoted real statute would be more impressive and would
be giving legal advice.

## In the voice branch

The unmerged `sherrykisilu-microsoft-voice-layer-elevenlabs` branch contains the most
explicitly argued cut in the repo.

**Live microphone capture.** Speech to text takes an audio file through `--audio-in`,
not a live stream. The branch README gives three reasons in one sentence: `groundwork`
has no UI and no audio capture, adding one would mean pulling a platform specific
recording dependency into a toolkit that is otherwise pure Python and stdio, and the
interesting engineering is downstream of the transcript either way. The third reason is
the one doing the work. A microphone would make the demo feel finished and would
change nothing about whether the grounding survives the audio, which is the actual
claim the branch is making.

**Streaming synthesis.** The whole answer is synthesised after the agent finishes, so
the wait is proportional to answer length rather than starting immediately. Listed as a
limitation, not solved.

**The official ElevenLabs SDK.** The client is a small REST wrapper over two documented
endpoints, which is why the unit tests can fake the HTTP transport and the live tests
skip without `ELEVENLABS_API_KEY`. The cost is that it tracks a thin slice of the API
and nothing more.

**The voice extra in CI.** The `voice` extra is not installed in CI at all, so the
offline suite keeps running with no secrets in about a second. The voice layer is kept
off the critical path on purpose.

## The cut that is really an unfinished thing

**Live runs.** The recordings in `evals/recordings/` are hand authored rather than
captured from live runs, because there was no API key on the machine where this was
built. The README says so. This is the one item on this page I would not call a scope
cut, because nothing was traded for it: the live path is implemented and documented and
simply has not been exercised end to end. It is listed here because an interviewer will
find it, and the right answer is that the replay gate is real and the live gate is
unproven, not that the live gate was out of scope.

## What comes back first, and why in that order

This is a sequencing argument, not a wish list. Each item is ordered by what it
unblocks, and each one has a trigger already named somewhere in the repo.

**First: one live run against the real API, recorded.** Everything else is uncertain
until this happens, because the replay baseline is currently compared against nothing.
It is first not because it is the biggest value but because it converts several open
questions into measurable ones at once: whether the hand authored recordings are
representative, whether the suite passes when the model actually chooses, and what a
live run costs. Until then the disagreement rate between replay and live is unknown
rather than zero.

**Second: make a skipped scorer visible as a skip.** Small, and it is a code change, so
it is out of scope for this directory. It comes second because it is the cheapest fix
to the one place where the repo's reporting is more flattering than its prose, and
because the first live run is what makes `judge` capable of running at all.

**Third: a third domain.** The core being reusable is the central claim and two
domains is the minimum evidence for it. A third is the designed falsification test:
if it cannot be added without changing the core, the claim is wrong and I would rather
find that out than not. It is third rather than first because it is a day of work and
it tests a claim that is currently plausible, whereas the live gap tests a claim that
is currently unsupported.

**Fourth: write tools, with an approval step.** This is where the product stops being a
demonstration, and it is deliberately last. It needs the live gate, because an agent
that can change a system cannot be evaluated only against recordings, and it needs a
third domain's worth of confidence that the read only boundary was a choice rather than
a crutch. Doing it earlier would mean building an approval story on top of an
evaluation story that has not been run live once.

Merging the voice branch does not appear on this list. It is complete, tested and
documented on its own branch, and merging it is a decision about what the repo's front
page should claim rather than a piece of work.

*Inference:* the ordering above is mine. The repo names the triggers and the gaps, in
the README's "what this is and is not" section, in the playbook's handover questions,
and in the voice branch's limitations, but nowhere does it sequence them. The claim
that write tools should come after the live gate specifically, rather than alongside
it, is a judgement, not something the repo states.
