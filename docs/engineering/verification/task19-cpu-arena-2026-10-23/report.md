# TASK-19 — CPU chat arena and optional compatible providers

23 October 2026. Completed the remaining external-provider comparison path and exposed verified CPU training bases alongside their candidates. Existing local Chat streaming, conversation history, system/template/decoding controls, stop/regenerate and project-scoped arena are reused.

## Actual bounded Mac run

A fresh isolated database imported the exact five-file public SmolLM2-135M base at revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. Ten authored source groups were published through the actual setup command. One CPU worker completed three real FP32 full-SFT updates. Base and candidate remained drafts; no quality improvement or promotion was claimed.

The CPU base's bare `{source, files}` snapshot is now listed by actual capability/access checks, without requiring imported/managed metadata. The completed candidate points to that exact base. Both initially reported `load_tested: false`; actual generation later changes their load evidence. Candidate weights: `022d348b24f344f9a50be627a302d5c1d96061e6a36580286c809532ed46bca6`.

The compatible endpoint was a second actual HTTP request to this Mac's self-hosted ModelAnvil completion API, pinned to the base model UUID and an explicit separate scoped credential. The primary local side used the changed candidate weights. This exercises real pretrained model inference through the provider transport; it is not a third-party provider, internet/TLS deployment or production qualification. No paid service was called.

A real browser at 1440 and 390 pixels enabled the installed target through administrator Privacy controls, selected the candidate and external base, inspected destination/credential labels before Send, sent the same prompt with the keyboard, streamed both actual outputs, saved exact settings/requests and recorded an automated fixture tie vote. The vote tests product persistence, not independent human preference quality.

For “A telescope collects”, both sides consumed 3 input and generated 8 output tokens. The base returned “light from a star and records the colors”; the candidate returned “light from distant objects. The” with the original whitespace preserved in the receipt. This anecdote is not an accuracy evaluation. Recorded timing and actual/provider-reported counts are retained separately from any qualification claim. The self-hosted provider's requested and reported model UUID both match the exact base. Upstream weight identity remains unverified for general providers.

Browser Stop after response headers reached a durable cancelled inference record and withheld partial conversation autosave. The actual API additionally executed a system prompt with a local ChatML override, refused an input repeating a word 4,000 times instead of truncating, and rejected the provider after its target approval was revoked. The final fixture policy is offline with no approved external target. Both temporary fixture API credentials were revoked and its owned servers stopped.

## Scope, privacy and integrity

Installed targets are scoped by tenant/project and contain endpoint, requested model and credential ID. Actual secrets are in a separate server-only key setting, excluded from public catalog/policy/diagnostics, conversations and inference records, and redacted in Django's error settings. The browser never receives a provider key. Default target approval is empty; an administrator approves exact installed targets and the user selects one in Chat. Offline mode overrides approval.

Provider requests do not use environment proxies, netrc, cookies or redirects. HTTPS is required except literal loopback HTTP with DEBUG. Bounds include requested output tokens, message/output characters, socket/read deadlines and stream/event bytes. Invalid usage, non-text/tool output, changed reported model identity, incomplete/error streams and redirects fail closed. Missing usage stays null; counts are provider-reported and no billable amount is invented. Current key/role/target/offline/configuration is rechecked before publishing every event. Previously transmitted content cannot be recalled from the provider.

Saved pairs verify exact input/output digests and matched generation settings, retain public endpoint/model/credential snapshots and remain project/principal scoped. Blind output labels are randomized until voting; the selecting user already knows the candidate set. External pairs cannot enter the local independent review workflow or authorize formal held-out/release qualification. Settings and destination remain inspectable after voting.

## Evidence and checks

[Setup/training receipt](setup-report.json), [real browser receipt](browser-report.json), [actual API/ledger/source hashes](wire-report.json). Screenshots were visually inspected at desktop and phone widths, with no horizontal overflow. Real unit/integration tests use an HTTP server rather than mocked provider replies to exercise default refusal, cross-project isolation, administrator permission, actual Bearer transport, live revocation, credential rotation, disconnect, redirects/error redaction, missing/malformed usage, stream bounds, immutable informal votes and exact generated output matching.

Integrated backend: 1,078 tests passed with 13 optional environment skips in 169 seconds. Frontend: 228 tests passed; production and Storybook builds passed. Django system and migration checks passed. The 19 focused provider/privacy/OpenAPI tests passed when rerun after the full suite without a competing CPU inference process. An earlier concurrent test correctly refused a busy device; its refusal is retained in the logs. Migration `core.0007_external_chat_providers` and `runners.0019_external_chat_providers` follow main's GRPO migration. Required remote CI must pass on the exact PR head before merge.

Reproduce provider transport checks with `python manage.py test modelanvil.api.test_external_chat modelanvil.api.test_privacy`; run the existing model-workspace suite with the pinned optional inference environment. Operator setup and the exact approval/data-destination flow are documented in [the private data policy](../../private-data-policy.md#optional-compatible-chat-providers). The local fixture harness, full logs and screenshots are also retained in the task's evidence directory; its private credential file is excluded.
