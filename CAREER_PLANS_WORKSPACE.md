# Career Plans workspace and daily recorded spend

Career Plans uses one composer for questions and proposed plans. Optional planning inputs remain local drafts until an explicit AI action. The saved plan is the main workspace; version-specific plan assistance is separate from the global Career Coach. Older chat and plan routes remain valid. Existing proposal review, citations, cancellation, output budgets and request tokens remain in use. There is no automatic paid retry.

## Checklists and versions

`GET/PATCH /api/career-coach/plans/{id}/progress` read/write an account-owned `coach_plan_progress` entity. PATCH requires an expected revision and a valid milestone/optional step. A conflict never overwrites another window. The interface retains the unsaved checkbox choice and saved totals on failures, with reload, retry and discard controls.

Step identities depend on the milestone kind/title, its occurrence, normalized step text and duplicate occurrence. Exact unchanged steps inherit self-reported completion from the selected source version. Changed steps begin unchecked; older versions retain history. Old chat milestone states are used as read-only fallback when no dedicated checklist exists. Legacy writes update the current compatible version. Checklist records participate in backup validation/remapping, restore, chat deletion and selective plans cleanup. Completion is never Profile evidence.

Optional `plan_ref` action context validates the owned plan, version, milestone and step before a paid action. The server includes that version's saved progress and relevant conversation; source and sharing permissions are checked again. Saving a reviewed proposal creates a version, never an automatic progress update. Global Coach saved-plan projections include current checklist progress, labeled as generated plans and self-reported completion.

## Daily estimate

`GET /api/usage/today?tz=America/Phoenix` aggregates the authenticated account's existing usage ledger. It performs no provider call, recovery, repricing or AI request. Account settings `usage_timezone` and `daily_spend_warning_usd` choose the day boundary and warning; zero or absent warning means off. Settings are included in the existing backup profile projection. The amount is an estimate from recorded token/tool costs, not a provider invoice. Partial, pending and wholly unpriced records stay distinguishable; wholly unknown cost is not zero.

The separate rectangular indicator above Career Coach refreshes on visible 60-second intervals, focus, completed app processing, midnight and warning-setting changes. Account-bound responses and cleanup prevent old account amounts remaining visible. Clicking opens Usage & costs with the current day/timezone. Neutral below 80%, orange from 80%, red from 100%; accessible descriptions include the percentage and state. Warning thresholds never affect task permission, cancellation, confirmation or retry behavior.

No reminders, calendar integration or hard cap are introduced. Installed localhost is outside deployment scope. Verification uses fictional accounts and simulated providers only.
