# CPU character evaluation reference

Policy id: `cpu-character-eval-reproduction-v1`.

This note and `reference-report.json` are the saved reference. They pin the protocol that `modelanvil.runners.eval_worker.evaluation_worker_executor` is checked against: initialization seed, training samples, step count, greedy CPU decoding, scorer, and held-out cases. They contain no measured completion, score, accuracy, weight hash, spread, or tolerance.

The rule that turns a later three-run spread into a tolerance is `scripts/cpu-character-eval-reproduction-policy.json`. That file stores the rule, not a tolerance value. A failing check does not change this policy id. A wider envelope needs a new policy id committed before a new set of three repeat runs.

The claim is reproduction of this pinned CPU character evaluation. It is not a quality result, and it is not production or hardware qualification.
