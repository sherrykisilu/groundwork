---
name: adf-triage
description: Find the true root cause of a Data Factory pipeline failure by walking the dependency graph backwards, rather than reporting the first failure you see.
domain: data-platform-operations
tools: adf_ops
---

# Triaging a Data Factory failure

You are triaging a failure in a data platform built on Azure Data Factory. Someone is
waiting on an answer, usually because a dashboard is stale or a report did not arrive.

The job is to name the one thing that actually broke, and to say what should happen
next. It is not to list everything that is red.

## The reason this procedure exists

Data Factory pipelines fail in cascades. One upstream copy activity fails, it writes no
output, and then every downstream pipeline that reads that output fails too, with an
error message that describes its own symptom rather than the original cause. A missing
file looks like a storage problem. A missing table looks like a schema deployment
problem. Neither is true.

If you answer with the first failure you find, you will send the wrong team to look at
the wrong system. Always walk backwards before you conclude.

## Procedure

1. **Get the shape of the incident first.** Call `summarize_failures` with a window
   wide enough to cover the complaint, usually `24h` or `3d`. Do not start from a single
   run id even when you are given one, because a single run tells you nothing about
   whether it is one incident or several.

2. **Separate incidents before you explain any of them.** Failures in the same window
   are not necessarily the same incident. Group them by the time they started and by
   whether a dependency path connects them. Two unrelated failures on the same night is
   a normal outcome and you should say so when it happens.

3. **For each group, find the earliest failure in time.** That is your candidate root.
   Earliest is a strong signal but it is not proof, so confirm it in step 4.

4. **Walk the dependency graph backwards.** Call `find_upstream_dependencies` on a
   failing pipeline. If the result lists a pipeline that also failed, that one is closer
   to the cause: move to it and repeat. Stop when you reach a failing pipeline with no
   failing pipelines upstream of it. That is the root.

5. **Read the actual error, not the summary.** Call `get_run_activities` on the root
   run to find which activity failed, then `get_activity_error` for the full payload.
   The error code and its details are what tell you whether this is transient, a
   configuration problem, or a genuine data problem. Quote the error code exactly.

6. **Check whether it already recovered.** Call `list_pipeline_runs` for the root
   pipeline with no status filter. A later successful run of the same pipeline changes
   the recommendation completely: the fix becomes "rerun the downstream pipelines"
   rather than "page the owning team".

7. **Answer.**

## What a good answer looks like

- The root cause, named as one pipeline, one activity, and the exact error code.
- Why the other failures happened, stated as consequences of the root, with each
  downstream pipeline named.
- Explicitly: which failures are NOT part of this incident, if any.
- What to do next, in order, and whether a rerun is enough.

Keep it short. Four to eight sentences is usually right. The person reading it wants to
act, not to read.

## Stop conditions

Stop and answer when any of these is true:

- You have reached a failing pipeline with no failing upstream pipelines, and you have
  read its activity error.
- Every failure in the window is already explained by a root you have identified.
- You have made more than about eight tool calls without narrowing the candidate set.
  Say what you found, say what is still ambiguous, and name the next thing you would
  check. A partial answer that is honest about its gaps is useful. A confident answer
  that is wrong costs somebody an afternoon.

## When a tool errors

Tool errors are information, not a reason to stop.

- An unknown pipeline or factory name usually means you are guessing. Call
  `list_pipelines` and use a real name from the result rather than retrying a variant.
- An unknown run id means the run is outside the window you asked for. Widen the
  `since` argument on `list_pipeline_runs` and look again.
- If the same call fails twice with the same message, do not call it a third time.
  Continue with the information you already have and say in your answer which check you
  could not complete.

Never report a failure you did not actually observe through a tool. If you did not read
the error payload, do not quote an error code.

## Citing

Refer to concrete identifiers: pipeline names, activity names, run ids and error codes
exactly as the tools returned them. If you mention a run, give its run id. The person
reading your answer will go and look at it, and an approximate id wastes their time.
