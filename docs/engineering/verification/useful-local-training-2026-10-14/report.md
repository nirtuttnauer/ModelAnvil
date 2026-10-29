# Useful local training defaults — 14 October 2026

The guided flow now recommends complete passes over a custom dataset and configures the training recipe automatically. A real run on this 48 GiB Apple computer completed 288 updates in 180 seconds. Six reworded library-policy questions produced the expected policy details, and browser chat returned the same correct loan-renewal answer with its default settings.

## Recommended behavior

- This Mac uses the verified SmolLM2-1.7B-Instruct snapshot with rank-16 LoRA across attention and feed-forward projections. Apple computers below 32 GiB and other supported GPU installations use the smaller 135M instruction model with full SFT. Model identity and instruction tuning are documented in the [official model card](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct).
- Adapter datasets with fewer than 100 training examples receive six passes; other datasets receive three. Only training rows determine the update count. Each pass uses every training example once in a reproducible shuffled order.
- The large adapter profile uses AdamW at 2e-4; the small full-SFT profile uses 2e-5. Gradient norm is clipped at 1. The verified native chat template trains assistant answers and their end tokens while masking prompts.
- Three spaced checkpoints bound disk use. Validation loss selects the candidate used by chat and download, including an earlier checkpoint when it scores better. Missing validation data produces an explicit limitation.
- Settings remain optional. The three-step setup check is labeled as too short to assess quality. Dataset guidance asks for varied question wording and accurate answers; review shows actual splits, the recommended passes and a rough time estimate.

## Actual run and answer checks

The [CSV fixture](library-policy-varied.csv) contains 60 examples covering 12 fictional library policies, with five question wordings per policy. The published split was 48 training, six validation and six test rows. Validation and test rows were excluded from optimization. The six additional question strings in [trained answers](trained-answers.json) were absent from the CSV and evaluated using the exact local inference implementation, greedy decoding, native model formatting and a 64-token output limit.

| Check | Observed result |
| --- | --- |
| Training execution | Managed Apple GPU worker; durable job succeeded; 288 updates |
| Elapsed training time | 180.25 seconds including model loading and checkpoints |
| Trainable parameters | 18,087,936 adapter parameters; base weights frozen |
| GPU tensor allocation | 7,197,467,648 bytes at checkpoints; this excludes driver/cache allocations |
| Validation loss | 3.755 before training; 0.928 / 0.592 / 0.487 at updates 96 / 192 / 288 |
| Selected candidate | Update 288, which had the lowest measured validation loss |
| Loan renewal | Sign in and choose Renew beside the loan |
| Library-card documents | Photo identification and proof of address |
| Returns after the desk closes | Includes the outdoor return box, although it also repeats the front-desk option |
| Digital books | Digital catalogue and library card number |
| Cancel a hold | Open Holds and choose Cancel |
| Study room | Book from the library website |

[Training evidence](final-training-evidence.json) records the source revision, recipe, optimizer, seed, checkpoint metrics and candidate identity. The [completed screen](17-shuffled-training-completed.png) shows the automatic result. [Browser chat](18-final-browser-chat.txt) verifies that **Try your model** selects that candidate, generates the renewal answer and saves the conversation.

A preceding run selected update 192 instead of its final update. Its actual browser download was 3,497,294,120 bytes, containing the verified base, rank-16 adapter, native tokenizer and provenance identifying update 192. [Download evidence](download-evidence.json) records the inspected archive. The final shuffled candidate was loaded from committed artifacts for these answer checks; its ZIP was not independently loaded.

## Regression checks and limits

The full backend suite passed: 852 tests, with nine skips. All 167 frontend tests passed; production and Storybook builds passed. Django system checks, migration-drift checks and whitespace checks passed. New regression coverage includes reproducible shuffle/resume ordering, train-only epoch calculation, step limits, assistant end-token masking, best-checkpoint selection, hardware model selection and coexistence with older managed workers. Logs are stored alongside this report.

This is evidence for a narrow personalization task, not a broad accuracy benchmark. Validation examples share the policies present in training, so their loss measures new wording of known information. The answer check is small, and the model still repeats both return options when asked about a closed desk. Reliable deployment needs a larger independent set of realistic questions. Defaults cannot repair incorrect or insufficient examples. Examples remain limited to 128 tokenizer tokens; longer examples receive repair guidance rather than silent truncation. The smaller-model fallback was exercised locally earlier in this session, but the final shuffled large-model plan was qualified on this Mac only.
