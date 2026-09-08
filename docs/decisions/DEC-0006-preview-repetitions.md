# DEC-0006 — Preview repetition schedule

* **Status:** Accepted (measurement clarification; changes no target or sample condition)
* **Deciding role:** implementation, following handoff v0.2 §5
* **Affects:** §12.0 sample and pass calculation

## Decision

Qualification schedules **36 independent warm preview requests — three per locked
clip — in addition to** the 36 warm final runs and 12 process-cold final runs.

The benchmark plan therefore contains 84 runs for a 12-clip sample:

| Run kind | Per clip | Total |
| --- | --- | --- |
| Warm final | 3 | 36 |
| Process-cold final | 1 | 12 |
| Warm preview | 3 | 36 |

## Why

§12.0 states a warm preview p95 target but enumerates repetitions only for the
final-output runs. A p95 needs a defined sample size, so the preview repetition
count had to be fixed before timing rather than after seeing results.

Handoff v0.2 §5 records the clarification directly: "Use 36 independent warm
preview requests, three per locked clip, in addition to the final-output runs.
Record this as a measurement clarification in the decision log before
qualification; it changes no target or sample quality condition." This decision
is that record.

Matching the warm-final repetition count also makes the two p95s directly
comparable: both select the 35th of 36 sorted observations under the nearest-rank
rule (DEC-0007).

## Enforcement

The evaluator emits a blocking `ELIG-REPETITIONS` finding when a plan schedules
anything other than 3 warm / 1 cold / 3 preview repetitions per clip, so a
qualification attempt cannot quietly run a smaller preview sample.
`animalite benchmark run` accepts `--preview-repetitions` for development runs;
using a non-conforming value makes the run permanently exploratory.

## Not covered

"Independent" means a separate request measured on its own clock. §12.0 also
requires the combined preview+final time to be reported when a user flow executes
both; that combined-flow measurement belongs with the integrated UI path
(Package D) and is not implemented here.
