# groundwork as a product

This directory documents the product thinking behind `groundwork`. It changes no code.
Everything in it is traceable to something already in the repo: the source, the eval
suites, the READMEs, the engagement playbook, or the git history. Where I had to infer
intent rather than read it, the line is marked `Inference:` so you can disagree with it
specifically rather than with the whole document.

Four documents, in the order they are worth reading.

| document | the argument it makes |
| --- | --- |
| [problem.md](problem.md) | Who this is for, read off what the repo pays for rather than off a persona. The user is an engineer who has to prove an agent works to someone else, in an environment where they cannot get a key, a budget or production data on day one. |
| [decisions.md](decisions.md) | Six decisions that could have gone the other way, each with the alternative rejected, the price actually paid, and the evidence that would make me reverse it. |
| [not-built.md](not-built.md) | What was cut and why, including the one decision in the voice branch that was argued down in writing. Ends with the sequencing argument for what comes back first. |
| [measurement.md](measurement.md) | What the eval suite can observe, what it provably cannot, and what I would instrument before claiming this works. No adoption numbers, because the repo cannot produce any. |

The shortest version of the whole thing: the hard part of putting an agent on a real
system is not the model, it is that nobody can say what a correct answer looks like.
`groundwork` is an argument that you write that definition down first, as executable
cases that assert on actions rather than on wording, and that you make the whole thing
runnable by someone who has no API key.

If you read one, read [decisions.md](decisions.md).
