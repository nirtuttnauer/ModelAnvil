# Formal blind preference review

Formal campaigns reuse actual completed local Chat comparisons. Informal arena votes and imported response text are not independent preference labels. This path creates one frozen batch per campaign, with randomized A/B presentation and separate reviewer assignments. Closing that batch completes the formal campaign even if the legacy maximum-cycle cap is larger.

## Create and assign

Generate and save local response pairs in Chat with matched prompt/decoding settings. The server verifies their actual completed inference records, input/output digests, distinct response text and current model/tokenizer manifest identity. External-provider pairs are excluded. The selecting user has already seen the model set and cannot be an assigned blind reviewer.

Create a manual preference-ranking campaign in Annotation with nonempty versioned review guidelines. A manager selects **Assign generated pairs**, one to 32 unused comparisons and two to eight distinct active project reviewer credentials. Where credential owners are known, they must represent distinct user accounts and cannot own the credentials that generated the pair. Guidelines, pair/model pins, A/B mapping and reviewer assignments are frozen. Another batch requires another campaign.

An optional published source revision binds each raw single-user prompt to exactly one eligible training row, retaining its source group, sample ID, manifest digest and provenance. Validation/test/audit source groups are excluded, including training rows sharing a protected group. Without a dataset binding, the canonical message digest identifies the authored prompt group. Current protected evaluation prompts/groups are refused again during review and export.

## Review and adjudicate

Assigned reviewer credentials receive only the prompt and randomized candidate A/B text. Identity mapping, model/configuration provenance, informal votes and peer labels are withheld by the server regardless of client blind flags. Related conversations and comparison endpoints also withhold formal-pair mapping from reviewers. Original response text is preserved; self-identifying response content and knowledge acquired before assignment cannot be undone by metadata blinding. Operationally independent reviewers still require independent people and appropriate access management; distinct credentials alone do not prove that.

Reviewers choose A, B, tie or abstain and give a nonblank rubric reason of at most 2,000 characters. Explicit skips/rejections also need reasons. Their pending queue follows their own review history, so another person's submission does not hide assigned work. Optimistic global revisions reject stale corrections; every accepted correction appends a new immutable review record and preserves the prior decisions and original generated responses.

Conflicts do not stop other assigned reviewers. A manager can adjudicate only after every assigned reviewer has submitted a choice or explicit abstention for that pair. Adjudication appends another record; later corrections to an adjudicated choice require an explicit manager adjudication. Missing reviews and unresolved disagreements block closure. Coverage reports required/submitted/missing reviews, resolved pairs and unanimous pairs over the full pair denominator. Ties and abstentions can be explicit agreement, but never become binary training labels.

## Export and train

Closure freezes the approved snapshot and a checksummed `modelanvil.preference-pairs.v1` artifact. Binary choices carry exact prompt/chosen/rejected text; model manifest and tokenizer identity, original messages/settings/request IDs, rubric version, source provenance and full review revisions remain auditable. Ties and abstentions are counted separately and excluded from pairs. Changed or unavailable model, tokenizer, rubric or source pins withhold subsequent review/export rather than silently substituting inputs.

**Export preference pairs** downloads the verified stored data. Manager access is required for provenance exports. Compatible artifacts appear directly in Alignment's training-preference picker, without download/re-upload. Current CPU DPO/reward training additionally requires one to 32 unique pairs, responses up to 32 characters, prompt-plus-response up to 62 characters, supported character vocabulary and a separate held-out artifact. Formatted conversations, oversized text/provenance or empty binary sets retain their export and explicit incompatibility reason; they are not advertised as compatible training artifacts. Nothing is silently truncated. Publication does not certify label quality or authorize a model release.

## API

- `GET/POST /api/v1/labeling-campaigns/{id}/generated-pairs/`: manager options and assignment. POST accepts only `comparisons`, `reviewers` and optional `source_revision`.
- `GET /api/v1/labeling-batches/{id}/tasks/`: forced blind content and personal assignment/review state for formal tasks.
- `POST /api/v1/annotation-tasks/{id}/review/`: append a revision with `decision`, `human_label: {label, reason}` and `expected_revision`. `adjudicate: true` requires a manager. Initial formal choices require the currently assigned reviewer role.
- `POST /api/v1/labeling-batches/{id}/close/`: refuse missing/conflicting reviews, then freeze coverage, exclusions and preference bytes.
- `GET /api/v1/annotation-snapshots/{id}/preference-pairs/`: manager reads current-access-checked committed JSON bytes. The existing snapshot export retains full audit history.

The [bounded Mac receipt](verification/task22-blind-preferences-2026-10-23/report.md) records real generated pairs, automated reviewer/adjudicator fixtures, browser verification and actual one-step DPO/reward consumption. These are implementation/recovery checks, not independently collected human preferences or representative domain-quality qualification.
