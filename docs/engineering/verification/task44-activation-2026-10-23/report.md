# Activation baseline reconciliation, 23 October 2026

The fresh-environment [observation](baseline.json) ran the existing `scripts/measure_activation_baseline.py` on main e29325b with a new Python 3.12.15 virtual environment and current `requirements.txt`. Environment creation and pip installation were timed immediately before the script; pip cache was allowed. The installation duration and method were added to the script's report. No customer database or artifacts were used.

Eight activation regression tests passed in that environment. They cover immutable/idempotent decisions, reject and no-gain accept accounting, simulation/partial/missing-baseline exclusion, event allowlists and conflicting replays, role/project/tenant boundaries, UTC week boundaries and evidence invalidation, tenant deduplication, and setup/synthetic fixture rejection. No new counting implementation was needed.

Seven missing historical reports were restored only after matching their previously published SHA-256 values. The supported-capabilities index keeps those dates and appends the fresh CPU observation with exact artifact identities. Historical GPU evidence is explicitly pending requalification against the upgraded stack. This does not complete the hardware or customer-research tickets.

The observation records one unique team/candidate/evaluation reject decision and zero accepted improvements. Measurement remains local, external analytics is disabled, and public output contains no prompt, answer, credential or private artifact path. Download and human effort are unobserved, rather than zero. No retention rate is inferred.
