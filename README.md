# groundwork

Most "can an agent do this job?" questions do not fail on the model. They fail on
everything around it: the system has no clean interface, nobody wrote down the procedure
a good engineer follows, and there is no way to tell whether the agent got the right
answer for the right reason or a plausible answer by accident.

`groundwork` is a small toolkit for closing that gap, plus two worked examples in
completely unrelated domains to show that the approach is a pattern rather than a
one-off.

## The pattern

Four steps, in this order. The order matters: the evals come before the agent is any
good, because they are how you find out what "good" means.

```
  1. WRAP            2. WRITE             3. EVALUATE          4. HAND OVER
  the messy system   the procedure        the behaviour        the artifact

  MCP server         SKILL.md             eval suite           a repo the customer
  tools that map     the checklist a      cases that assert    runs themselves,
  to real nouns      competent engineer   which TOOLS were     offline, in CI
  and verbs          would follow         called, not just
                                          which words appeared
```

Everything in `src/groundwork/core` is domain neutral. Everything in
`src/groundwork/servers` is one domain. Adding a third domain means adding a server,
a skill and a suite, and changing nothing in the core.

## The two domains

**`adf_ops`** is pipeline operations, modelled on the public Azure Data Factory REST
API. Twelve pipelines with a real dependency graph, and a run history containing a
failure cascade: one upstream copy activity hits an HTTP 429, and three downstream
pipelines then fail with error codes that each look like a separate problem. A missing
file. A missing SQL object. A failed child trigger. The eval suite checks that the
agent walks the dependency graph back to the throttling error instead of stopping at
the first failure it sees, and that it does not fold a genuinely unrelated incident
(an expired service principal secret, same night, different pipeline) into the same
story.

**`ke_compliance`** is grounded question answering: compliance obligations for small
businesses in Kenya, over a synthetic corpus with BM25 retrieval written in plain
Python. Different data, different failure modes. Here the agent fails by inventing an
obligation, by citing a section that does not exist, or by answering confidently from
general knowledge when the corpus does not cover the question. The suite checks
citations against what the tools actually returned, and checks that an out of scope
question gets a refusal rather than a guess.

Two domains, one core, one harness. That is the whole claim.

## Public API surfaces and synthetic data only

I work on data pipeline reliability tooling at Microsoft, which is why I understand
this problem shape. Nothing here comes from that work. The `adf_ops` server is built
against the public, documented Azure Data Factory REST API shape, and every pipeline
name, run, error message and timestamp in it is synthetic data generated for this
repo. There is no internal code, no internal pipeline, no internal query, and no
internal error taxonomy anywhere in it.

The `ke_compliance` corpus is also entirely synthetic. It is modelled on the general
shape of real small business obligations (register if you handle personal data, file
payroll deductions monthly, renew your permit annually) but it does not reproduce any
statutory text, and the specific deadlines, thresholds and document ids are invented.
Every document carries a disclaimer, the tool descriptions say so, and the server
returns it alongside results. It is a retrieval demo. It is not legal advice.

## Quickstart

No API key needed. The whole eval suite runs offline.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"

.\.venv\Scripts\groundwork run-eval evals\adf_ops.yaml --provider replay
.\.venv\Scripts\groundwork run-eval evals\ke_compliance.yaml --provider replay
```

```
adf_ops  (provider: replay)
+-------------------------------------------------------------+
|      | case                 | scorers | tools | turns |  ms |
|------+----------------------+---------+-------+-------+-----|
| PASS | root_cause_cascade   |     8/8 |     4 |     5 | 139 |
| PASS | separate_incidents   |     6/6 |     6 |     5 | 141 |
| PASS | already_recovered    |     6/6 |     1 |     2 | 128 |
| PASS | skipped_is_not_cause |     4/4 |     2 |     3 | 131 |
| PASS | tool_error_recovery  |     5/5 |     4 |     5 |  10 |
+-------------------------------------------------------------+

5/5 cases passed in 1.2s
```

Other things you can do:

```powershell
groundwork list-skills                 # the skills in skills\
groundwork list-scorers                # the ten scorers a suite can use
groundwork serve adf_ops               # run one MCP server over stdio
groundwork run-eval evals\adf_ops.yaml --case root_cause_cascade --verbose
groundwork run-eval evals\adf_ops.yaml --report report.md --json result.json
```

To run against the real API instead, set `ANTHROPIC_API_KEY` and pass
`--provider anthropic`. Add `--record` to save the transcripts as new recordings, and
`--judge` to enable the LLM judge scorer.

## How the offline mode works, and what it does not prove

`ReplayProvider` replays recorded model turns from JSON in `evals/recordings/`. The
important detail is that it replays **only the model side**. The tool calls still
execute for real, against the real MCP servers over a real stdio transport. So an
offline run still catches a broken server, a broken fixture, a bad tool schema, or a
citation that the tools never actually returned. It will not catch the model changing
its mind, because in replay the model has no mind to change.

That is the honest trade. You get a suite that runs in about a second, costs nothing,
is byte for byte reproducible, and can gate a pull request with no secrets in CI. You
give up live model behaviour, which is what `--provider anthropic` is for. On a real
engagement you run replay on every commit and live on a schedule.

## The scorers

Ten of them, in `src/groundwork/core/evals/scorers.py`. The interesting ones:

| scorer | what it asserts |
| --- | --- |
| `tool_called` | a specific tool ran, optionally with matching arguments |
| `tool_sequence` | tools ran in a given order, as a subsequence |
| `cites_source` | every citation in the answer was actually returned by a tool |
| `no_tool_errors` | the agent did not leave errors unhandled |
| `max_turns`, `max_tool_calls` | an efficiency budget |
| `contains`, `not_contains`, `regex` | the usual text checks |
| `judge` | an LLM scores the answer against a written rubric |

`tool_called` and `cites_source` are the two that earn their keep. Text scorers tell
you the answer *reads* right. `tool_called` tells you the agent took the right action,
which on an operational task is the only thing that matters. `cites_source` is a
deterministic grounding check that costs nothing: it pulls every `DOC-XXX-01#S2` shaped
citation out of the answer and fails unless that exact string appeared in a tool
result. It caught two hallucinated citations in the hand written recordings while this
was being built, which is the best argument for it on offer.

`judge` skips and passes when no API key is present, so offline CI stays green. That is
a deliberate choice and a real weakness: a suite that leans on `judge` is weaker offline
than it looks. The deterministic scorers are the ones that gate.

## Layout

```
src/groundwork/
  cli.py                     the groundwork command
  core/
    skills.py                SKILL.md loader, YAML frontmatter plus markdown body
    agent/
      providers.py           ModelProvider protocol, AnthropicProvider, ReplayProvider
      mcp_client.py          stdio MCP client, tool aggregation across servers
      loop.py                the tool calling loop
    evals/
      case.py                suite and case schema
      scorers.py             the scorer registry
      runner.py              concurrency, retries, timing, recordings
      report.py              rich table and markdown report
  servers/
    adf_ops/                 domain A, synthetic ADF shaped pipeline operations
    ke_compliance/           domain C, synthetic Kenyan SME compliance corpus
skills/
  adf-triage/SKILL.md
  compliance-answer/SKILL.md
evals/
  adf_ops.yaml, ke_compliance.yaml, recordings/
docs/ENGAGEMENT.md           how to take this to a new domain in a day
```

## What this is and is not

It is a demonstration of a delivery pattern, with enough real machinery that you could
point it at a new system on a Monday and have something defensible by Friday. The core
is genuinely reusable: two unrelated domains share it without either one bending it.

It is not a product, and a few things are deliberately small. The corpus is six
documents, not six hundred, so BM25 is the right call and a vector index would be
overkill. Both servers are read only, because an agent that writes needs an approval
story and that is a different project. There is no auth, no rate limiting and no
multi-tenancy: real deployments need all three. The judge scorer needs a key to mean
anything. And the recordings are hand written rather than captured from live runs,
because there was no API key on the machine where this was built, so the live path is
implemented and documented but has not been exercised end to end.

## Running the checks

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pytest
```

214 tests. They cover the skill loader, every scorer, the BM25 implementation, the
dependency graph traversal, the replay provider, tool error recovery in the loop, and
an end to end pass that spawns both MCP servers over real stdio transports and calls
their tools. CI runs the same commands plus both eval suites, with no secrets.

## Licence

MIT.
