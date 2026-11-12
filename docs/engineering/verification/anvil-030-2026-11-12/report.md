# ANVIL-030: first outside user kit, 12 November 2026

Label: `local`. Ticket: ANVIL-030 (Aftur TASK-107).

## What changed

- `README.md`: a new section, "Who it is for and how to try it", sits after the introduction and before "Measured RAG reference", and the top navigation gains a "Try it" link to it.
  - Each capability claim is one of the evidence-labeled rows in "Current capabilities" (ANVIL-016, #127), stated at that row's level: dataset preparation, CPU and Apple GPU post-training, evaluation with an accept or reject decision, and export with a separate-process load are all integrated execution.
  - CUDA, ROCm and XPU training profiles are named as configuration only.
  - The RAG numbers are called small correctness checks next to a random-vector baseline.
  - The memory figure ("about 2 GB of free memory") comes from ANVIL-029, where the 3-step LoRA golden path peaked at 1.40–1.42 GiB RSS and 1.85–2.25 GiB of sampled container memory.
  - The section links to the golden path instructions and to the new feedback form.
- `.github/ISSUE_TEMPLATE/golden-path-feedback.md`: a feedback form for the golden path. It asks for the commit SHA, the command, whether the run finished, the machine and Python version, timings, the last 30 lines of output, and what was unclear. It asks people not to paste private data or tokens.

## Wording review

`rg -n -i 'best|production-ready|qualified|enterprise|SSO|pro version' README.md` on this branch:

| Word | README matches | Matches in the new section |
| --- | --- | --- |
| best | 0 | 0 |
| production-ready | 0 | 0 |
| qualified | 1 | 0 |
| enterprise | 0 | 0 |
| SSO | 0 | 0 |
| pro version | 0 | 0 |

The one `qualified` match is in the existing Compose reference paragraph, which says the development stack is not a qualified deployment. The new section says "built for", not "best at". It makes no mention of a paid version, open core, SSO or a team add-on.

`python scripts/capability_labels.py --check-readme` and `python scripts/rag_report.py --check-readme` both exit 0. The golden-path README install and train blocks are unchanged.

## Not done

- The ticket's detail asks the README to link to the ModelAnvil product page on Nir's site (`/modelanvil`). That site is registered but not connected yet, so no link was added; a dead link would be worse than none. Add it when the page is live.
- Nothing was sent to any outside user. The feedback form appears on GitHub's new-issue page only after this change is merged, and merging is Nir's decision.

## Gates

The shared gate records are in [gates.md](gates.md).
