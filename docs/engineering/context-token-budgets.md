# Runtime context token budgets

Context Lab uses the selected qualified CPU reference model's verified tokenizer and role-lines template to count the **complete serialized input**. A successful pinned compilation enforces:

```text
input tokens + declared output reserve <= configured limit <= pinned runtime limit
```

Model/tokenizer artifact hashes, tokenizer identity, runtime contract and template pins are rechecked before compilation. The runtime limit comes from the qualified model bundle (up to 64 tokens in this bounded CPU profile). Output reserve is 1–32 tokens for these runtimes. Even an empty template plus reserve must fit when saving a pinned recipe. Compilation never executes a model; measured paired experiments separately verify actual inference usage against the compiled count.

Unbound recipes retain a clearly labeled compatibility estimate. Their receipts report `runtime_validated: false` and no runtime limit; they cannot execute measured model comparisons. Giving a pinned recipe to the bare compiler without its verified tokenizer is refused. Diagnostic callers also go through the shared pinned compiler.

## Required content and overflow policies

Nonempty **priority 1** content is required. It cannot be omitted for the total budget or truncated by a per-block cap. A required block exceeding its cap fails explicitly, including under the legacy priority-trimming policy. Empty templates remain inactive until supplied with content.

The editor supports these explicit choices:

- **Fail on overflow:** refuse a complete serialized input that exceeds the available input budget.
- **Omit optional evidence only:** omit only `evidence` blocks with priorities 2–10, lowest priority first. Required evidence and other categories stay intact. If those remaining categories or template overhead cannot fit, compilation fails.
- **Omit lowest priority blocks:** retain the existing, explicitly selected compatibility behavior for optional priorities 2–10 across categories. Required content still cannot be removed.

A declared cap on an optional block applies before total-budget handling and explicitly truncates its text using the same counter. Caps count standalone model encoding, including its tokenizer overhead. The receipt records original/capped token counts. A capped block may then be omitted by the selected total-budget policy; `included_in_final: false` distinguishes that case. These separate decisions are visible in the UI. A cap too small even for standalone encoding fails instead of pretending to fit.

Summarization/compression has no qualified executor in this profile and is refused. No implicit summary or category replacement is generated.

The compiler validates the final serialized prompt again after all omissions, including when no optional blocks remain. This prevents template/generation-prefix overhead from escaping an empty trim loop. Runtime overrides use the same checks; changing raw text cannot bypass the budget.

## Receipt and UI

The compile API preserves its existing count/mode/pin fields and adds `budget`: exact input, output reserve, total reserved tokens, configured and runtime limits, remaining capacity, validation status and selected overflow policy. Omitted entries name the actual block/category and reason. Truncation entries record caps and whether the block is in the final input.

Per-block chart allocations are **changes in serialized prefix counts**. They account for template and tokenizer behavior and sum to the final input count when blocks are present. An empty compiled template has its full input count with no block allocation; they are not independent encodings that can be added to predict a new prompt. The full-prompt count is authoritative.

In Context Lab, select the pinned model, output reserve and policy when authoring an immutable recipe revision. Each block has an optional cap. The compiled token-budget receipt shows the invariant and all cap/omission decisions. The compile action waits for a saved revision to finish loading. Compilation errors include the reason and never display a successful runtime-validation receipt.

This qualifies only the supported local CPU reference profiles. It does not qualify arbitrary imported model tokenizers, GPU runtimes, compression quality, prompt-injection resistance or answer quality. See the [actual runtime verification report](verification/task72-token-budget-2026-10-23/report.md).
