# Career Explorer Goals Plans and Offer Context

Career Explorer supports deliberate handoffs into the existing career workspace. Browsing occupations, saving bookmarks, reviewing goals and opening message drafts make no AI request.

## Explorer and Profile

Add as Career Goal opens a review form. Existing linked occupations open their saved goal for editing. Saving preserves the O*NET code, title, dataset version and revision, without changing the account's automatic AI setting. Bookmarks and goals are independent.

Discuss with Career Coach and Explore in Career Plans open an editable question with a visible occupation preview. Sending explicitly shares that occupation even if automatic Career Goals context is off. Other goals/bookmarks are not included by that selection. Context revisions are checked before dispatch, and the submitted snapshot is saved with the conversation. These descriptions and ambitions are not qualification evidence.

## Cover letters

Use selected Career Goals for this letter starts off. Apply goal selection creates motivation proposals through the existing review workflow; goals cannot enter generation before approval. Users can correct the proposed wording for free. Goals explain intent, not completed training or experience.

Turning the selection off removes its motivation from future generation without rewriting historical letters. Changed goals require a refreshed selection and review. Backup imports retain historical sources but disable automatic reuse of imported per-letter goal selections until reviewed again. This setting never enables goals globally or changes resumes.

## Career Plans

Ask & explore keeps normal questions, starters and saved chats. My plans lists the same saved roadmap records, with next steps and access to the original conversation. Previous versions are optional; progress remains attached to stable milestone identities.

Build a plan accepts an objective and optional target, available time, budget and specifically selected goals. Timelines can use flexible periods or dates, while legacy 30/60/90-day plans retain their meaning. Generated plans remain proposals until Save reviewed plan. Users can edit milestone wording, steps, periods, target dates and effort before saving. Source references remain attached. Suggested schedules are distinguished from exact deadlines supported by fetched official source quotations. No reminders or applications are scheduled, and completing a milestone does not create Profile qualifications.

## Offers

Offer details is available for Offer/Accepted applications and remains reachable after a later status change. It stores optional compensation terms, location, working arrangement, dates and notes in a separate account-owned application-linked record. Blank values remain unknown. It does not compute winner scores, infer raises or equate remote work with work-life balance.

Preview offer for Career Coach shows the exact details to share. A second saved offer can be selected explicitly. Discuss this offer with Career Coach opens a draft; sending is separate. Offer records are excluded from automatic resume evidence and Career Coach retrieval. Their contents must not enter public research queries. Existing application metadata can remain available to the Coach without revealing offer compensation.

## Technical boundaries

- All writes and reads are account-scoped. Goals, cover workspaces and offers use revision checks; plan saves check the originating chat revision.
- `application_offer` is an additive entity kind; no destructive schema migration. Backups validate its application association and remap its deterministic identity on import.
- Occupation metadata imported from historical backups is preserved without forcing the current dataset to match. Normal new/changed links require a valid current snapshot.
- New AI actions reuse existing account credentials, task deduplication, cancellation, recovery and usage tracking. Context is validated both before queuing and before provider dispatch. Cover-letter generation and review calls explicitly disable automatic paid retries.
- Raw Work Styles answers and private application disclosures stay outside these flows. Existing consent rules for approved summaries and separately authorized Coach reports remain intact.
- No embedding-based matching, new Journey, personality ranking or independent offer-scoring workflow was added.

Provider-dependent acceptance uses fictional fixtures during automated and browser tests; actual live paid-model quality requires a separate optional user check. The operator's user checklist and protected rollback records live outside the public repository.
