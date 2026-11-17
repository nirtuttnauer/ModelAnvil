| Configuration | Wall s (median, range) | Tokens/s (median) | vs baseline | Peak allocated MiB | vs baseline | Resident MiB | Optimizer state KiB | Held-out loss | Δ vs baseline | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 2.904 (2.901–7.845) | 7467 | 1.00× | 2563.7 | 1.00× | 196.3 | 3600.0 | 5.40099 | 0.000% | pass |
| gradient_checkpointing | 3.667 (3.582–3.671) | 5914 | 0.79× | 1506.2 | 0.59× | 196.3 | 3600.0 | 5.40099 | 0.000% | pass, equivalence pass |
| bf16_compute | 2.344 (2.341–2.389) | 9252 | 1.24× | 1833.4 | 0.72× | 187.8 | 3600.0 | 5.40096 | 0.001% | pass |
| packed | 5.470 (5.012–9.279) | 3965 | 0.53× | 2904.0 | 1.13× | 196.6 | 3600.0 | 5.40099 | 0.000% | pass, equivalence pass |
| adafactor | 3.151 (3.109–3.202) | 6883 | 0.92× | 2557.8 | 1.00× | 190.5 | 228.8 | 5.52564 | 2.308% | fail |
| force_fused_attention | 2.885 (2.871–2.910) | 7516 | 1.01× | 2405.2 | 0.94× | 196.3 | 3600.0 | 5.40102 | 0.001% | pass, equivalence pass |
| low_memory | 3.127 (3.095–3.173) | 6935 | 0.93× | 1176.4 | 0.46× | 181.7 | 228.8 | 5.52564 | 2.308% | fail |
| low_memory_packed | 2.893 (2.886–2.961) | 7495 | 1.00× | 1085.5 | 0.42× | 182.0 | 228.8 | 5.52561 | 2.307% | fail |
| reference_one_sample_per_step | 7.093 (6.922–8.302) | 3057 | 0.41× | 596.0 | 0.23× | 196.3 | 3600.0 | 5.17009 | 4.275% | not_applicable_different_update_count |
