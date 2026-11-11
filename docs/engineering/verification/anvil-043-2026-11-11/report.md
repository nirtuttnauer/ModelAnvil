# ANVIL-043 gitleaks triage, 11 November 2026

Label: `local`.

`gitleaks` 8.30.1 reports 370 `generic-api-key` findings on the working tree of `4dd5060e632bae598003bf3a51a474709fe8c7ac`. The same 370 were introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165` ("Harden development defaults and stop digest false positives"). None of those 370 fingerprints are on `reviews/ANVIL-017-gitleaks-history.md`. Every one is tag `decoded:unicode` at decode depth 1: the value is stored as JSON `\u00XX` escapes, and gitleaks 8.30 decodes the escapes before the rule runs. The decoded value is not present as literal text in the file.

No finding is unresolved. No finding is a live credential. `.gitleaks.toml` allowlists only the five groups below, each with a one-line reason, and only for `generic-api-key`. The stock rules stay in force. A literal generic key in a verification JSON file is still reported. The 36 historical findings that remain are all on the ANVIL-017 list.

Raw gitleaks reports are not committed. Each finding is identified by rule, path, commit, line, and the SHA-256 of the decoded value. Those rows are in `findings.json`. There are 84 distinct values across 370 findings.

## Groups

| Group | Count | Files | Decoded shape | Allowlist |
| --- | --- | --- | --- | --- |
| D | 248 | 48 | 64 lowercase hex | file digests |
| H | 42 | 15 | 64 lowercase hex | `host_key()` digest |
| U | 66 | 32 | UUID | tokenizer id |
| R | 13 | 2 | UUID | reviewer principal id |
| F | 1 | 1 | 32 lowercase hex | fencing identifier |

Rule for every row: `generic-api-key`. Commit that introduced every row: `75e2565a83b4b0cf96aebe793a9da6823e67d165`. The same bytes are on `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

### D — pinned-file SHA-256 digests (248)

The JSON field name is a pinned filename or an explicit digest name: `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`, `added_tokens.json`, `tokenizer_digest`, `api_source_digest`, `candidate-api-verification.json`, `current-candidate-api.json`, `openapi.json`, or `access.py`, including evaluator-prefixed copies of the tokenizer files. The decoded value is 64 lowercase hex characters, which is a SHA-256 digest. Entropy of every finding in this scan is between 3.57 and 3.97, the range of hex text. These are the digests ANVIL-017 stored as JSON unicode escapes so a stock scanner would not read them as credentials. gitleaks 8.30 decodes that encoding.

Allowlist reason: SHA-256 digests of pinned files and `host_key()` coordination hashes in verification JSON. gitleaks 8.30 decodes the JSON unicode escapes added in 75e2565 and `generic-api-key` matches the digest.

### H — `host_key()` coordination hashes (42)

`host_key()` in `modelanvil/device_admission.py` returns the SHA-256 of `hostname`, uid, and the local device-lock directory. The verification JSON stores that digest beside `device`, `packages`, and `capacity_source` under accelerator pins. It is not key material. The decoded value is 64 lowercase hex characters. Fifteen verification files carry it.

The same allowlist entry as group D covers this shape. The match text must be the `host_key` field followed by 64 hex characters, and the path must be under the verification JSON paths below.

### U — tokenizer ids (66)

The field is `tokenizer_id` or `tokenizer`. The decoded value is a UUID. It names a tokenizer record in a verification report. It is not a credential.

Allowlist reason: UUID tokenizer ids and reviewer principal ids (`api_key:` plus the API-key row primary key, not the credential) in verification JSON. gitleaks 8.30 decodes the JSON unicode escapes added in 75e2565.

### R — reviewer principal ids (13)

`modelanvil/annotation/preferences.py` builds reviewer ids as `api_key:` plus `ApiKey.pk`. `ApiKey.id` is a UUID primary key. The model stores only `secret_hash`. `generate_api_key()` returns a distinct `mkv_` plaintext that is shown once and is not in these reports. The 13 hits are in `docs/engineering/verification/task22-blind-preferences-2026-10-23/exported-preferences.json` and `browser-report.json`, on fields `reviewer` and `reviewer_id`. The decoded value is the UUID, and the source text keeps the literal `api_key:` prefix in front of the escapes. gitleaks matches because the field text contains `api_key` and the decoded UUID looks like a generic secret.

The same allowlist entry as group U covers this shape. The match text must be `api_key:` followed by a UUID.

### F — fencing identifier (1)

One hit, `docs/engineering/qualification-reports/task4-browser-run.json` line 349, field `fencing_token`. The decoded value is 32 lowercase hex characters. `Job.claim` generates a fencing token with `secrets.token_hex(16)` as a lease guard for one running attempt. ANVIL-017 already triaged the pre-encoding hit on this same path and line: "32-hex fencing identifier in a qualification report. It is not a live credential." The 75e2565 commit only changed the encoding, which gave the hit a new gitleaks fingerprint, so it is absent from that list. The qualification run is finished. This ticket does not treat the re-encoded value as a live credential and does not rewrite history.

Allowlist reason: 32-hex fencing identifier in the finished task4 browser qualification report. ANVIL-017 QA ruled this same hit is not a live credential. gitleaks 8.30 decodes the JSON unicode escapes added in 75e2565.

The allowlist path is only that file, and the match text must be the `fencing_token` field followed by 32 hex characters.

## Allowlist scope

`.gitleaks.toml` extends the default rules. Each allowlist sets `condition = "AND"`, `regexTarget = "match"`, and `targetRules = ["generic-api-key"]`. A finding is ignored only when the path and the match text both agree.

Paths for groups D, H, U, and R:

- `docs/engineering/verification/` JSON files
- `docs/engineering/qualification-reports/` JSON files
- `docs/engineering/supported-capabilities.json`

Path for group F: `docs/engineering/qualification-reports/task4-browser-run.json` only.

Checked with gitleaks 8.30.1 on a temporary tree, not committed:

- A unicode-escaped 64-hex value under `tokenizer.json` in `docs/engineering/verification/` is not reported.
- The same 64 hex characters stored literally under `tokenizer.json` in that tree are not reported either. That is the pre-encoding form of group D, which is the class ANVIL-017 already accepted.
- A literal generic assignment in `docs/engineering/verification/probe.json` is still reported.
- The same literal assignment in a Python file is still reported.

## History that stays reported

`gitleaks detect --source . --log-opts=--all` with this config exits 1 with 36 findings, all rule `generic-api-key`, none decoded. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. They sit outside the allowlist paths, or they are not the match shapes above:

- `modelanvil/runners/training/hf_runtime.py` (7)
- `scripts/audio_candidate_infer.py` (7)
- `modelanvil/runners/training/vlm_math.py` (4)
- `modelanvil/runners/training/audio_runtime.py` (4)
- `scripts/vlm_candidate_infer.py` (4)
- `modelanvil/runners/training/audio_math.py` (3)
- `scripts/verify_cpu_export.py` (3)
- `docs/engineering/verification/manual-qa-2026-10-12/local-workflows.md` (1)
- `modelanvil/rag/chunking.py` (1)
- `modelanvil/core/test_selfhost.py` (1)
- `modelanvil/context_lab/test_context_lab.py` (1)

Without the config, the same history scan reports 781 findings: 411 whose fingerprints are on the ANVIL-017 list, and the 370 from `75e2565a83b4b0cf96aebe793a9da6823e67d165`. The working-tree scan without the config reports 370. With the config it reports 0.

## Gate results

Gate commands and counts are recorded after this classification, in the files next to this report.
