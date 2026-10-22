# 003 Fine-tune decision loop

- **Date:** 22 October 2026
- **Status:** Accepted for the next product slice
- **Owner:** Product

## Problem

The welcome screen promises one job: fine-tune an LLM on this computer. The 21 October capability baseline can do that for two pinned SmolLM2 profiles. Activation, though, is an explicit accept or reject after a verified candidate-versus-baseline comparison. The guided path stopped at chat and download. Native-template evaluation of the exact guided adapters was still open, and the rest of the workspace still presented the unfinished R1 platform as equally ready.

Applicable product intent: the local activation measures in `docs/engineering/supported-capabilities.md`. The PRD and roadmap remain the long-range specification.

## Options

1. Keep building labeling, RAG, and Context Lab in the 11 October backlog order.
2. Treat the near-term product as private fine-tune and decide, and finish that loop before more surface area.

Option 1 adds breadth before a new account can earn the product's own success metric. Option 2 uses the comparison and decision APIs that already exist.

## Decision

The next slice is **private fine-tune and decide** for a small team on their own machine.

- Score the exact guided candidate with its native chat template against the base model on the held-out split, or on a short question list the user confirms. Plain-prompt CPU evaluation does not substitute for that candidate.
- Record accept or reject through the existing decision API. Recording a choice does not deploy the model. Chat and download are inspection, not evidence of improvement.
- A synthetic training fixture and a three-step setup check cannot be accepted as an improvement.
- Default navigation is Overview, Training, Chat, Evaluation, and Datasets. The other destinations stay available under Advanced.
- Dataset Bank's default list shows sources that can be acquired. Email accounts can reset a password. The project owner can invite one teammate who can record the decision. An approved labeling snapshot can start guided training. Automatic draft, retrain, and next-batch orchestration stay unbuilt.

Scratch pretraining, alignment recipes that do not run the guided candidate, RAG answer generation, the cluster explorer, quantization, release promotion, broad Dataset Bank acquisition, and billing stay later until this loop is the normal outcome of the welcome flow.

## Consequences

Workers that train a guided model also need the evaluation runtime, including the Apple GPU for the 1.7B profile. The managed service dispatches evaluation jobs as well as training jobs. An accept still requires measured task accuracy above the baseline. Loss, chat preference, and a short setup run do not qualify.

## Verification

API regressions cover native-template selection, held-out case extraction, setup-check and synthetic rejection, password reset, and the one-teammate invitation. A fresh-account GPU journey is not claimed from those tests.
