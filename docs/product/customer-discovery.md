# Private AI customer discovery

23 October 2026 · TASK-43 · Audience: small teams building private AI products

**Decision: revise before selecting a commercial use case.** No interview notes,
observed customer workflows, or partner commitments were supplied with this work.
The eight interviews, five observed workflows, named buyer, and five willing
design partners remain outstanding. The use-case decision stays open. This packet
prepares the research; it does not establish customer demand or complete TASK-43.

The starting candidates are text classification, structured extraction, and
constrained responses, as recorded in Aftur source `PRD-727037b1`. Select one only
after observing a customer's existing task. Keep the other candidates available
if the evidence does not support the first hypothesis.

## Evidence and completion gates

| Gate | Evidence required | Current state |
| --- | --- | --- |
| Team interviews | Eight dated interview records with permission to retain the findings | No records supplied |
| Observed workflows | Five observed attempts, including failures, current outputs, active effort and runtime | No records supplied |
| Selected task | Named user and buyer in a restricted record, current alternative, data rights, hardware limits and a declared success measure | Open |
| Design partners | Five distinct teams explicitly agreeing to a permitted pilot scope | No commitments supplied |
| Discovery decision | Completed comparison rubric, chosen task and a go or revise rationale grounded in the records | Revise; recruitment and observation are still required |

An interview is evidence of an interview, not consent to a pilot. Interest in a
demo is not a partner commitment. Product tests and the local activation baseline
are engineering evidence, not customer interviews or willingness to pay. Keep
TASK-43 open if a required gate remains unmet, even after this packet is merged.

## Recruit participants

The founder owns recruitment. Seek teams with a recurring text task, a person
responsible for its outcome, and permission to discuss its present workflow.
Include teams for which a prompt change, retrieval, or an existing script may
already solve the problem. Record that outcome rather than steering every team
toward training.

Use these slots to track missing research. Empty cells are unfilled slots, not
people, completed interviews, or scheduled appointments.

| Slot | Restricted evidence reference | Interview date | Workflow observed | Candidate task | Next action |
| --- | --- | --- | --- | --- | --- |
| I01 | — | — | — | — | Identify participant |
| I02 | — | — | — | — | Identify participant |
| I03 | — | — | — | — | Identify participant |
| I04 | — | — | — | — | Identify participant |
| I05 | — | — | — | — | Identify participant |
| I06 | — | — | — | — | Identify participant |
| I07 | — | — | — | — | Identify participant |
| I08 | — | — | — | — | Identify participant |

Draft invitation for the founder to adapt and send after choosing a recipient:

> We are researching how small teams improve private AI workflows. Would you be
> willing to walk us through a recent classification, extraction, or constrained
> response task, including what failed and how you checked the result? A redacted
> example or screen share is enough; please do not send private data or credentials.
> We would like about 40 minutes. Participation does not commit you to a pilot.

No outreach is sent by this workflow. Contacting participants requires a separate
human instruction.

## Run the interview and observation

1. **Permission and context, 5 minutes.** Confirm the purpose, what may be noted,
   who can read it, and whether recording is allowed. Default to notes without
   recording. Ask the participant to use redacted or synthetic material.
2. **Recent task, 10 minutes.** Ask for the last occurrence, the person doing the
   work, frequency, cost of a mistake, current tool or script, manual corrections,
   and how the team knows the answer is acceptable. Distinguish recollection from
   something directly observed.
3. **Observed attempt, 15 minutes.** Have the participant perform the existing
   workflow. Time setup, active work, waiting and checking separately. Record the
   task, current alternative, output verdict, error category, recovery and who
   judged the result. Include failed and abandoned attempts.
4. **Permissions and deployment, 5 minutes.** Ask who owns the data and labels,
   whether use for training and evaluation is permitted, which systems data may
   leave, retention requirements, available hardware, memory, and compute budget.
   Do not copy the customer's examples into Git or Aftur.
5. **Buyer and next step, 5 minutes.** Identify the user, budget owner, approval
   process, timing, current spend and support expectations. Ask whether they want
   to discuss a bounded pilot. Record their answer without converting it into a
   commitment or invented price.

For every observation, retain a restricted record containing: interview ID,
date, consent and permitted use, user role, buyer role, task definition, current
alternative and version, example count and approximate lengths, hardware limits,
timings, output verdict, failures, and the participant's own success criterion.
Mark unknown fields explicitly. Link a permissioned evidence reference in the
research log; do not include names, emails, recordings or raw examples in Git.

## Compare the three candidates

These are task definitions to investigate, not claims that a runtime is qualified
for a customer's data. Record the actual labels, schema or response rules with
the participant before evaluating any model.

| Candidate | Concrete task to observe | Success measure to declare with the customer | Alternatives to compare |
| --- | --- | --- | --- |
| Text classification | Map each input to the customer's fixed label set, including an abstain path where needed | Per-label precision and recall, critical error limits, correction effort and latency | Existing rules or classifier, current prompt, then a trained candidate |
| Structured extraction | Produce the customer's declared fields from an input with explicit missing-field behavior | Schema validity, field accuracy, critical field errors, correction effort and latency | Existing parser or manual entry, current prompt, then a trained candidate |
| Constrained responses | Produce an answer that follows explicit style, format and allowed-content rules | Rule pass rate plus human task correctness, severe failures, correction effort and latency | Current prompt and templates; retrieval for changing knowledge; then a trained candidate if justified |

Use the same rubric for each candidate. Score only observed evidence: **0** means
the requirement fails, **1** means mixed or limited evidence, and **2** means
consistent evidence across observed teams. An unmeasured field is **unknown**,
not zero. Every score needs an evidence reference and the number of teams behind
it. Do not total scores until every row is known.

| Dimension | Evidence needed for a score of 2 | Classification | Extraction | Constrained responses |
| --- | --- | --- | --- | --- |
| Recurring need | Teams demonstrate a repeated task with a concrete consequence of failure | Unknown | Unknown | Unknown |
| Existing pain | Observed attempts show measurable correction effort, failures or avoidable cost | Unknown | Unknown | Unknown |
| Evaluation clarity | Users agree on a reproducible output verdict and severe-error definitions | Unknown | Unknown | Unknown |
| Data readiness | Owners confirm rights and enough usable examples for the declared protocol | Unknown | Unknown | Unknown |
| Deployment fit | The declared privacy boundary and hardware fit a measured supported profile | Unknown | Unknown | Unknown |
| Buying process | A named budget owner describes a plausible decision path and value | Unknown | Unknown | Unknown |
| Pilot commitment | Teams explicitly agree to a bounded pilot with recorded scope | Unknown | Unknown | Unknown |

Data rights, privacy, hardware fit and an evaluable success criterion are hard
gates. A high total cannot compensate for a failed or unknown gate. Use scores to
compare candidates, then record the rationale; they do not automatically select
a winner. Freeze any task-specific numeric thresholds before running a comparison.

## Confirm pilot scope and the selected task

Keep contact details, named users and named buyers in a founder-controlled,
access-restricted record outside the repository and Aftur. Use opaque partner IDs
and permitted aggregate findings here. Share a restricted link only with people
who are authorized to read it.

| Slot | Restricted commitment reference | Consent date | Permitted task and data use | Hardware and privacy boundary | Pilot status |
| --- | --- | --- | --- | --- | --- |
| P01 | — | — | — | — | Unfilled |
| P02 | — | — | — | — | Unfilled |
| P03 | — | — | — | — | Unfilled |
| P04 | — | — | — | — | Unfilled |
| P05 | — | — | — | — | Unfilled |

A commitment record must state the agreeing team and person, user and buyer,
consent date, task, permitted data use, environment, duration, success and stop
criteria, support owner, retention/deletion expectations, and withdrawal route.
Leave commercial terms open until explicitly discussed; agreement to research
does not authorize spending, publication or model/data reuse.

When evidence supports a candidate, complete this decision record:

| Field | Value |
| --- | --- |
| Selected task and intended user | Open |
| Named user and buyer | Pending; restricted record required |
| Current alternative and measured pain | Pending observation |
| Data owner, permissions and allowed processing | Pending confirmation |
| Hardware, capacity and deployment constraints | Pending measurement |
| Frozen success metric and severe-error limits | Pending agreement before evaluation |
| Independent evaluation and protected source groups | Pending task-specific protocol |
| Five committed partner IDs and scope references | Pending commitments |
| Founder decision, date and supporting evidence | Revise on 23 October 2026; selection remains open |

## Review the evidence and decide

At each founder review, count completed interviews, observed workflows and
distinct committed partners. Check the restricted evidence references, permissions
and current rubric. Record contrary evidence and missing fields alongside the
positive findings.

**Go** requires eight interviews, five observed workflows, one fully specified
task, five willing design partners with permitted scopes, and a completed rubric
supporting that choice. **Revise** applies if any gate remains unmet, demand is
weak, permissions fail, or a simpler alternative already meets the customer's
needs. State which assumption changes and what observation could resolve it.

The current decision is **revise** because participant evidence and commitments
are outstanding. The founder's next action is to identify participants and gather
permissioned records using this packet. Once those records exist, update the
rubric and selected-task record, attach sanitized evidence to TASK-43, and review
its remaining acceptance criteria. Merging the preparation alone does not pass
the discovery gate or validate the paid-pilot assumptions in TASK-56.
