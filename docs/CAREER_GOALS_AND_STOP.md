# Career Goals and controlled AI actions

Profile → **Career Goals** stores ambitions and future interests separately from professional qualification evidence. Saving is local to the account and free of AI requests. Career Coach uses a frozen copy for each conversation; editing Profile never rewrites previous advice or roadmaps. An explicit request to save revised goals can update Profile, with exact authorization and concurrent-revision checks.

Application Assistant offers **Use Career Goals** only for clearly open-ended motivation or fit questions. It is off by default. Goals support interests and direction; reviewed professional sources alone support qualification claims. Every generated answer still needs review before use, and an aspiration-containing answer is not automatically saved as professional evidence. Resumes, cover letters, factual screening fields and deterministic filling do not read Career Goals.

Career Coach starts with a question and editable starters. Opening the screen, selecting a starter or reading history never calls AI. Ordinary advice can use saved evidence. Current/external questions trigger one bounded research step before the final answer. Conference organizers, agendas, certification terms and current labor-market sources may be researched through the protected public-fetch helper. Each action is bounded to three model requests, one of which can perform at most four web-search calls; at most six cited public pages are fetched. Unsupported or unavailable current information is not silently invented.

## Stop means discard this run

One shared banner reports each action. **Stop** requests server cancellation, closes the provider HTTP transport and prevents subsequent stages. The UI confirms completion before reporting a stopped state; a lost connection remains unconfirmed. Usage already incurred is retained, and unreported charges remain unknown.

Business changes use task-scoped SQLite overlays. Reads within the task see its candidate changes; ordinary workspace reads see committed records. The final transaction validates original records and publishes the overlay together with successful task completion. No SQLite transaction remains open across a provider request. Concurrent manual edits cause the generated changes to be rejected rather than overwriting newer work.

Cancellation discards the overlay, including partial matching batches, revisions and document artifacts stored in records. Combined approval-and-generation actions stage their Profile changes as part of the same run. Submitted questions remain browser drafts; a first-message chat exists in committed history only after success. A completion that wins the final transaction is reported as already finished. Late rendering threads cannot reopen task-scoped writes after the task stops. Startup removes abandoned staging without replaying paid requests.

The usage ledger, task status and minimal failure/recovery metadata use a separate committed lane. A failed job-match run may retain its unknown in-flight request marker but does not publish new assessments. Explicit provider failures also leave previous generated results intact. Existing directly uploaded inputs remain user-owned inputs.

## Interfaces

- `GET/PUT /api/profile/career-goals`: account-owned text and revision; writes require the expected revision.
- `POST /api/career-coach/chats/new/actions`: a submitted first question; chat/message creation commits only with success.
- Existing chat edit supports `use_current_profile_goals`.
- `POST /api/tasks/{id}/cancel`: owner-scoped and idempotent; assistant request IDs use the `assistant:` prefix.
- Task status adds cancellation capability and `cancelling`/`cancelled` states. Existing task recovery remains read-only.
- Application assistance adds `draft_short_answer` and an explicit `use_career_goals` boolean.


## Profile summaries and optional AI context

Profile → Work Styles displays a private assessment summary immediately and a saved or suggested working-preference summary. Edit preferences opens a separate editor. Only an explicitly reviewed, saved and enabled work-preference summary enters automatic AI context; raw answers and assessment descriptions do not.

Career Goals opens as a saved summary. Edit Career Goals reveals the direction note and goal cards. Save Career Goals saves the current revision and collapses the editor only after success. Hidden editors remain mounted so tab switches and collapsing preserve drafts.

Use Career Goals for AI guidance is off by default, including for older records without an explicit choice. Saving text alone does not enable it. Enabled goals can support Career Plans, Career Coach retrieval, personalized discovery and skills plans as aspirations. Turning it off and saving removes automatic Profile-goal context from subsequent requests, including old planning chats, without rewriting historical messages or plans. Goals typed into a conversation remain part of that conversation. The optional application motivation-answer helper retains its separate, initially-off choice. Account backups retain goals and the explicit preference; older backups default off.

Citizenship & sponsorship and Private application answers start collapsed. Their existing encryption, review and explicit save rules remain unchanged. The global Career Coach launcher has a hover/focus explanation; opening it alone makes no AI request.
