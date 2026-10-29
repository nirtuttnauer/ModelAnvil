# Fresh account default training acceptance 15 October 2026

A new account completed signup, custom CSV upload, default local training and saved model chat. The different dataset describes a fictional coworking space, Harbor Hub. Its trained model returned the expected policy details for all six reworded questions, with conversation saving and reopening verified after a backend fix.

## Verified journey

The browser created an isolated workspace and first project, selected the recommended SmolLM2-1.7B Instruct model, recognized the CSV prompt and response columns automatically, previewed the examples, published the dataset and launched the recommended plan. No training or generation controls were changed.

The [60-example dataset](harbor-hub-support.csv) produced 48 training, six validation and six test examples. Six passes meant 288 updates on the local Apple GPU. Training completed in 199.42 seconds. Validation loss fell from 2.495 to 0.01565; checkpoint 288 supplied the candidate. A complete page reload restored the active run and its progress. [Recorded training evidence](training-evidence.json) contains the actual settings and checkpoint metrics.

**Try your model** selected the exact candidate and its native prompt format. Default chat used CPU inference, temperature 0, a 128-token output limit and seed 42. Reworded questions about opening hours, room booking, cancellation, invoices, lost cards and bicycle parking each returned the expected details and saved successfully. [Saved answer checks](saved-chat-answer-checks.json) include the actual responses and configurations. The [reopened conversation](14-reopened-conversation.txt) preserved the correct meeting-room answer.

## Fixes verified

- New training configurations select Recommended immediately. Before a dataset exists, the screen explains that the plan will be calculated after upload instead of displaying a custom 50-step plan or zero updates.
- Guided review uses the readable model name. Advanced model registration clears the previous guided label.
- Simple preflight keeps successful technical checks expandable, with launch visible. Blockers, warnings and expired approvals open the details automatically; advanced mode retains expanded checks.
- Completed runs place **Try your model** directly below progress, before exports and charts. The separate low-level inference check is expandable.
- Dispatch confirmation directs users to live progress instead of retaining an obsolete pending state.
- Conversation validation now accepts and preserves the chat UI's `blind` and `base-trained` comparison modes, while rejecting unsupported modes and unknown completion options. Previously, generation succeeded but automatic saving failed on `comparison_mode`.

The [updated completion screen](15-completed-run-actions.png) and browser snapshots accompany this report. A fresh configuration in a separate tab also showed Recommended with no manual step input. Development-service restarts were required after concurrent source changes and to load the backend fix; the saved training run remained intact.

## Regression results and scope

All 27 affected backend tests and 202 frontend tests passed. Production and Storybook builds passed, as did Django checks and whitespace checks. The Training Modes And Tabs interaction story passed, including expandable simple checks, shared advanced settings, preflight invalidation and keyboard tab navigation. Logs are stored in this directory.

This check establishes a working default flow for a narrow custom task on this Mac. The six questions use new wording for policies represented in training; this is not an independent general-accuracy benchmark. Full backend regression, export downloads and other hardware profiles were not repeated in this pass.
