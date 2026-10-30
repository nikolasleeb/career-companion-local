# Interview guides and saved practice

Interview Practice offers six formats and saved sessions. Behavioral includes STAR as an optional answer structure. Five bundled guides contain 33 original questions: Behavioral 10, Case/business 6, Domain/scenario 7 (one per broad career field), Presentation/portfolio 6 and Other 4. The sources support methods and formats, not a claim about question frequency or employer-specific questions.

## Guide and setup navigation

`GET /api/interview-practice/guides` is authenticated, read-only and requires no AI key. The versioned catalog and stable IDs live in `backend/app/data/interview_guides.json`. Source changes require manual review.

Guide routes use `tab=behavioral|case|domain|presentation|other`. Their `-setup` routes render a dedicated setup page without the guide beneath it. `tab=coding` retains Coding setup. The optional `topic` route value identifies a guide question; no private text enters the URL. Setup title, targeting, notes and PDFs stay in account-scoped drafts across navigation and reload.

Non-coding setup offers Guide question and Generate with AI. Guide mode requires explicit question selection; AI mode uses reviewed Profile evidence, the selected job/application and preparation notes/PDFs through the existing question action. The final Generate question & start practice button is the only paid trigger; selecting modes, reading guides and reloading make no AI request. Interrupted setup generation remembers its saved session and request token, allowing status recovery without duplicate sessions or a paid retry. An explicit retry reuses that saved session when context is unchanged. A question card preselects its ID, and general Start practice opens an unselected question choice. The prompt and approach guidance remain visible before the final Start practice session action. New Coding sessions retain the initial, explicit Generate question AI action. Saved-session workspaces expose no manual-entry, subsequent question-generation, narration, illustration-generation or practice-material-generation controls.

## Compatible session and question APIs

`POST /api/interview-practice/sessions` accepts optional `guide_question_id`; existing requests remain compatible. The starter and session save atomically with account ownership rechecked under the write lock. The response remains the saved session. Prompt, source IDs, catalog version and review date are snapshots under `origin: guide` and `guide_provenance`, separate from personal Profile evidence.

`POST /api/interview-practice/sessions/{id}/questions` accepts either a `guide_question_id` or the legacy `question` string, plus `expected_updated_at`. Exactly one source is required. Invalid IDs/type combinations create nothing. Guide selection repairs an older empty session in place. Legacy `star` maps to the Behavioral guide without changing the saved session kind. Active requests and stale versions prevent additions. The existing manual API remains available for compatibility, though its controls are removed from the workspace.

Existing generated/custom questions and legacy STAR sessions remain answerable. A selector appears for multiple saved questions. No schema migration or automatic AI action is introduced.

## Preparation and answer modes

All saved types use `tab=practice|feedback` with existing `item` and optional `question` identities. Links without a tab open Practice. Both view panels and the voice controller remain mounted while changing tabs.

Preparation precedes the editor/recorder. Behavioral past-experience questions and legacy STAR show a compact STAR reminder and optional four-field draft. Introduction, motivation, strengths and development guide questions use their own structures. Other formats use their relevant guide structure. Profile example selection and AI preparation guidance remain optional. Guidance uses editorial structure as advice, never as evidence of the user's accomplishments.

Typed STAR mode submits the four fields. Voice submits only the confirmed spoken transcript. Mixed submits that transcript with explicitly labelled typed notes/code. STAR planning notes remain preserved across modes and are not added to spoken content. Recording blocks navigation away from Practice. Stopping leaves an unsent in-memory buffer; raw recordings are not retained through page reloads.

## Transcripts and feedback

A raw generated transcript is displayed when an empty, unapproved `reviewed_transcript` exists. Approved nonempty text takes precedence only after `reviewed_at`; an edited browser draft, including deliberate empty text, is kept. Stale drafts remain unconfirmed and offer Restore generated transcript or an explicit choice to keep edits against the latest saved version. Neither action calls AI.

The flow is Record, Process recording, Check transcript, Review my answer. Processing makes transcription and delivery requests only after the explicit paid action. Processing, partial results, unusable transcription and delivery-only success have distinct states. No usable transcript means no spoken-content review. The transcript checkbox is required; Review my answer saves the confirmed transcript before sending the content-review request. Failed confirmation makes no content AI request. There is no separate Use reviewed transcript button.

Feedback shows the selected question's latest content review, followed by separate delivery observations for the latest saved recording, conversation controls and collapsed complete history. Content review evaluates relevance, structure, specificity, individual contribution, supported outcomes and clarity regardless of STAR use. Optional `reviewer_takeaway` defaults empty for older coaching snapshots and appears as What your answer communicates; it must be grounded in the response and must not predict hiring outcomes or infer personality/protected traits. Revise answer returns to the intact draft.

Request progress/cancellation uses the global progress area when present; local status/recovery remains visible otherwise. No disclosure hides essential recovery or errors. Checking saved results never retries a paid provider request.

## Retained history and boundaries

Saved questions, attempts, transcripts, materials, illustrations and source snapshots remain in history and account backups. Older material/image results are read-only. Previously submitted illustration/audio tasks retain status recovery and cancellation without new generation controls. Narration recovery can expose only an already-created temporary playback buffer; it does not start narration again.

Work Styles consent remains off for new sessions. Only the approved paragraph is shared when explicitly enabled; raw scores and private application answers remain excluded. New answer claims remain practice drafts until individually reviewed and approved as Supporting Details. Coding submissions are reviewed conceptually and are never executed.

Behavioral's ordered `further_reading_ids` reference three visible public links below its questions. They open in a new tab and are omitted from the collapsed source list to avoid duplicates. The U of A access note distinguishes the public guide from NetID access to Big Interview. Other source lists remain unchanged.

Verification uses fictional desktop accounts and simulated providers, with raw transcript assertions before any text editing, partial failures, stale drafts, all session types, navigation, recording buffers, confirmation order, request recovery, cancellation, history, backup/restore and account isolation. No paid user-account requests or mobile checks are required.
