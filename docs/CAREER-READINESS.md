# Career Readiness

Career Readiness lives under Resources between Explore Occupations and Action Plans.
It helps students identify possible directions, review a shortlist, assess their
preparation, and choose a next step. It uses one OpenAI Python Agents SDK agent,
with account-scoped read-only tools. The model chooses tools and follow-up
questions based on their results; the surrounding application controls access,
spending, cancellation, persistence, and review.

## Student workflow

Create a session with an exploration objective and optional interests, enjoyable
activities, preparation time and learning budget. Existing reviewed Profile
evidence follows the account's personalization settings. Career Goals remain
aspirations and approved Work Styles summaries remain preferences. Private
application answers, raw questionnaires and assessment scores are excluded.
Students can explore before completing Profile setup.

Explore directions proposes up to three catalog occupations. Review or replace
the shortlist, compare the directions, then select one to assess. The agent may
ask up to three useful questions; answers can be skipped. Statements about new
experience remain session self-reports until separately reviewed in Profile.

An assessment distinguishes demonstrated strengths, transferable experience,
uncertainties and proposed development priorities. It includes three sourced
next actions, without a fit percentage or hiring probability. Occupational
preparation is separate from specific employer requirements. Missing evidence
does not establish a missing skill.

Follow-up questions discuss a selected report. Reassessment first shows changed
inputs, then creates a new version. Historical reports are immutable. Shared
guidance can prepare Action Plans, Skills, Interview Practice and Career Coach
drafts. Career Goals and saved occupations use their existing review/save flows.
These handoffs do not start a paid request.

## Agent execution and evidence

The pinned `openai-agents` dependency is version 0.24.0. `Agent`, typed function
tools, a structured result envelope and `Runner` manage the agent loop. A narrow
Responses model adapter routes SDK requests through the existing account-scoped
HTTP transport. No global provider key, SDK-managed retry, remote session store,
hosted trace export, shell, browser-control or write tool is enabled.

Tools search and inspect occupations, retrieve reviewed professional evidence
and linked Supporting Details, inspect selected saved postings/comparisons,
retrieve guidance and learning resources, read published wages, and optionally
research official career sources. Search combines weighted full-text fields and
stemming; it is not semantic embedding retrieval. The leading search results
include occupation snapshots, allowing an undecided student to explore without
first naming an exact occupation.

References must resolve to supplied sources and literal excerpts. A terminal
punctuation mark added to a quote can be removed only when the remainder is an
actual source substring; words, omissions and negation are never repaired.
Strengths lacking reviewed professional support are omitted and disclosed.
A mistyped source ID is corrected only when its literal excerpt uniquely matches one source already provided to the run. Ambiguous or invented excerpts and unsupported numeric findings reject the generated result.
An assessment's structured schema requires exactly three proposed actions.
Resource topics are normalized to the learning catalog before handoff.

Public research is off by default. When enabled, server-created queries use an
inspected occupation's public title and an allowlisted focus, never raw Profile
or session prose. Existing official-source filters and protected fetch helpers
apply. Unavailable research is reported as a coverage limitation.

## Costs and recovery

Each explicit action permits four investigative model rounds and one final
response, eight application-tool calls, and at most one research request with
four search calls and six public page fetches. Default spending ceiling is $1
per action, adjustable before starting. Estimates use the configured model,
processing tier, response limit and the application's verified price catalog.
Each request reserves a conservative amount before dispatch. Reported usage
reconciles the reservation; unknown outcomes remain reserved. Usage is recorded
under Career Readiness, including nested research. A final-response allowance
is reserved before further investigation is admitted.

Opening, saving inputs and reading history are free. Stop closes active provider
work and discards task-staged results. Recovery checks status without repeating
a paid request. Revision/sharing conflicts preserve earlier reports. Repeated
tool calls are suppressed and investigation ends at its configured limits.

## Interfaces and lifecycle

The route is `#/career-readiness`, with session IDs in `item`.
`/api/career-readiness/sessions` supports owner-scoped session creation, listing,
detail, updates and deletion. Session `/actions` starts discovery, comparison,
assessment, follow-up and reassessment through existing background tasks.
`/actions/{token}` recovers an existing request. Session `/changes`, `/estimate`
and report `/handoff` endpoints are read-only.

Session, turn, report and research entities participate in backup/import,
account cleanup, deletion and storage quotas. Imports remap internal account
references. Reservation records are an independent financial lane, with foreign
key cleanup. Readiness reports enter Career Coach only through explicit sharing;
generated guidance never becomes qualification evidence. Sharing permissions
are checked again before handoffs and subsequent model requests.

## Verification and demonstration

`backend/tests/test_readiness.py` exercises the actual SDK Runner with intercepted
provider responses and fictional accounts. It covers free navigation, tool use,
versions, recovery, ownership, sharing revocation, cancellation, budget admission,
source validation and account lifecycle behavior. Existing coaching, planning and
interview tests protect the integration points.

`scripts/evaluate_readiness.py` provides 24 fictional scenarios and an optional
comparison with the existing Coach. It requires an explicitly supplied test key
file and enforces a cumulative spending ceiling in its output ledger. Use
`--workflow` on a targeted scenario to exercise comparison, follow-up and
reassessment. Live failures and rejected outputs remain inspectable; mocked
tests do not establish provider entitlement or response usefulness. Human review
should check whether citations support the conclusions and whether proposed
actions are useful before claiming a quality improvement.

For a short presentation, show an undecided student's sourced shortlist, review
the agent activity, choose a direction, inspect an assessment's evidence, and
prepare an Action Plans draft. Explain one uncertainty and show that reassessment
preserves the original report. Test desktop only.
