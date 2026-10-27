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


## Profile goals and Work Styles summaries

Career Goals uses a single entry form above the saved list. Save goal creates an entry and clears the form; Edit, Save changes, Cancel, Delete and ordering controls operate on individual saved entries. There can be one General statement and up to 30 specific goals. Existing overall-direction notes appear as a General statement without AI conversion or truncation. AI guidance is a separate explicitly saved, default-off setting. Aspirations never become qualifications.

Assessment at a glance is unchanged. Your Work Styles summary is an editable paragraph, limited to 250 words. Generate summary and Ask AI to revise are explicit paid actions using the account's own key and settings. Only optional work-comparison choices, saved work-style statements, the draft and user notes are sent; no questionnaire ratings, private assessment descriptions, personality scores or web search are included. Each request makes one model call, with no automatic paid retry. A proposal requires acceptance and review before Save summary; AI use stays off until explicitly enabled. Manual editing is free. Stop, task recovery and the usage ledger apply.

Citizenship and authorization status values are stored in the encrypted account-bound private vault, with compatibility accessors for existing application tools. Startup migration verifies encryption before removing the four plaintext settings fields. Old account backups can import these values into the vault; new ordinary exports omit the private fields. Historical records and older backups retain their original contents. Private section accordions start collapsed and use the same plus/minus headings as Resume content.

The privacy notice describes server-managed encryption at rest and isolation from other accounts. It does not claim end-to-end encryption: the server can decrypt data, and an administrator with server/key access could technically read it. Protected installation recovery requires the matching database and vault key. No key download or expanded sharing permissions are added.
