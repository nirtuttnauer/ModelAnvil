| Configuration | Wall s (median, range) | Tokens/s (median) | vs baseline | Peak allocated MiB | vs baseline | Resident MiB | Optimizer state KiB | Held-out loss | Δ vs baseline | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 2.936 (2.904–3.064) | 7385 | 1.00× | 2563.7 | 1.00× | 196.3 | 3600.0 | 5.40099 | 0.000% | pass |
| gradient_checkpointing | 3.605 (3.569–3.718) | 6015 | 0.81× | 1506.2 | 0.59× | 196.3 | 3600.0 | 5.40099 | 0.000% | pass, equivalence pass |
| bf16_compute | 2.337 (2.300–2.347) | 9278 | 1.26× | 1836.4 | 0.72× | 187.6 | 3600.0 | 5.40096 | 0.001% | pass |
| packed | 7.595 (7.037–13.576) | 2855 | 0.39× | 2904.0 | 1.13× | 196.6 | 3600.0 | 5.40099 | 0.000% | pass, equivalence pass |
| adafactor | 3.222 (3.110–3.490) | 6730 | 0.91× | 2557.8 | 1.00× | 190.5 | 228.8 | 5.52564 | 2.308% | fail |
| force_fused_attention | 2.878 (2.876–3.256) | 7536 | 1.02× | 2405.2 | 0.94× | 196.3 | 3600.0 | 5.40102 | 0.001% | pass, equivalence pass |
| low_memory | 3.124 (3.119–3.229) | 6941 | 0.94× | 1176.8 | 0.46× | 182.0 | 228.8 | 5.52564 | 2.308% | fail |
| low_memory_packed | 3.044 (2.889–3.274) | 7123 | 0.96× | 1088.1 | 0.42× | 182.0 | 228.8 | 5.52561 | 2.307% | fail |
| bf16_checkpointing | 2.969 (2.899–3.116) | 7305 | 0.99× | 1182.3 | 0.46× | 187.6 | 3600.0 | 5.40096 | 0.001% | pass |
| bf16_checkpointing_packed | 2.689 (2.645–2.874) | 8064 | 1.09× | 1091.5 | 0.43× | 188.0 | 3600.0 | 5.40103 | 0.001% | pass |
| reference_one_sample_per_step | 6.960 (6.760–8.458) | 3116 | 0.42× | 596.0 | 0.23× | 196.3 | 3600.0 | 5.17009 | 4.275% | not_applicable_different_update_count |
