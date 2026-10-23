# TASK-72: runtime context token budgets

Date: 2026-10-23. Base: main 786cab4 (PR39), normally merged into this branch.

Pinned compilation enforces exact serialized input + output reserve <= configured limit <= verified CPU runtime limit. Bare estimated counters cannot compile pinned recipes. An empty template must fit at save and compile time. Required nonempty priority-1 content fails explicitly if a block cap or total budget cannot preserve it. Named evidence omission can remove only optional evidence; explicit legacy priority omission remains available. Compression remains unavailable rather than inventing a summary.

## Actual runtime and browser evidence

The existing qualified local CPU model and tokenizer compiled 33 prompt characters into **35 input tokens** including its two special tokens. With **4 output reserve**, the receipt reports **39/64** reserved tokens and **25 remaining**. A real paired experiment reported baseline usage **35 prompt / 4 completion / 39 total**. The invalid required-block cap returned HTTP400 and failed the candidate before generation. Required system and question text remained intact. Optional evidence was explicitly capped from 242 to 100 standalone tokens, then omitted under the named evidence policy; the receipt records `included_in_final: false`.

Recipe 01a16727-c9ed-7168-9586-7c0f40fbd650; valid revision 01a16727-c9ee-7045-b324-0e6f1d2e0124; invalid revision 01a16727-cb4f-75ab-84df-7bc79409029a. Actual experiment 01a1672a-d0c0-73a5-884b-ad57510e8cc6. These are owned disposable QA data, with no customer quality claim.

Real application checks at 1440 and 390 pixels exercised authoring, compilation, cap/omission receipts and reload. One confirmation batch verified the loading guard and actual paired inference. No browser errors or horizontal overflow. The initial harness clicked before the saved revision loaded; the product now disables compilation during that transition. No additional visual iterations were performed.

- [Machine-readable actual evidence](browser-report.json)
- [Desktop confirmation](confirm-1440.png)
- [Mobile confirmation](confirm-390.png)

## Verification

- Full runtime backend: 1,017 tests passed, 6 optional skips (before merging PR39).
- Final integrated runtime context/authoring/feedback/privacy/OpenAPI regression: 50 tests passed.
- Final clean base runtime for the same selection: 50 tests passed, 2 optional runtime skips.
- Frontend: 226 tests passed; production and Storybook builds passed.
- Migration drift: no changes detected. OpenAPI mirrors include the named policy and budget receipt.
- Software regression cases cover empty-template overhead, impossible standalone caps, required caps under all policies, optional evidence-only selection, unknown policy, forged runtime limit, and exact real-tokenizer receipts. Existing unbound recipes explicitly report an estimate and no validated runtime limit.

Final-head CI separately runs the base backend, HTTPS production integration and real pgvector/embedding broker checks. No arbitrary imported model, GPU runtime, compression quality, prompt-injection resistance or answer-quality qualification is asserted.
