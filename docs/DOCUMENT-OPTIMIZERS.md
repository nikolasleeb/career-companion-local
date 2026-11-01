# Resume and Cover Letter optimizers

The application steps remain Posting → Comparison → Resume → Cover Letter → Finish. Route values such as `stage=letter` remain compatible. Saved historical documents and their original files are unchanged.

## Model choices and generation

Use the Writer & Reviewer control on either document page to choose two different approved models, their reasoning levels and speed. Choices are shared between Resume and Cover Letter and belong to the signed-in account; saving them makes no provider request. Posting/comparison and other features retain their existing AI settings. Each running task freezes its model settings through the existing account AI context. Each successful provider response records the actual model, document role, usage and cost metadata.

Resume optimization plans/selects confirmed evidence, drafts, independently reviews the rendered document, lets the original Writer revise once with that feedback, then independently checks the final document and audits its factual sources. At most one measured layout correction is allowed. Cover Letter uses draft, independent review, one Writer revision, factual audit and final independent review. Optional question preparation is a separate visible stage. Independent reviewers see only employer-facing document text, local layout/extraction checks and the posting. They do not receive the Profile, writer rationale or conversation. Reviews describe findings; they are not employer ATS scores or hiring probabilities.

A failed initial review does not cause another review attempt automatically. A source-valid draft may remain available with review unavailable; cancellation/factual-validation failures preserve the previous successful revision. Retrying generation or rechecking requires an explicit action. Small chat edits use the shorter existing factual/layout-validation path and mark the independent review outdated. Recheck reviews the exact revision without rewriting it.

## Questions, confirmation and continuation

Useful evidence questions appear in the document conversation. Create/Optimize pauses when questions need answers. Answers save without AI. Review answers proposes editable facts using exact original answer excerpts; approving saves existing reviewed Supporting Details with their valid Profile links and provenance. Resume approval resumes the waiting generation when no pending proposals remain; remaining unanswered questions can still pause it. Cover Letter confirmation uses the existing confirm-and-build path. Skip unanswered questions & Continue resumes with existing confirmed evidence. Opening a page, typing and saving answers do not start generation.

Professional Supporting Details require an existing valid record link and retain existing project/skill attribution rules. They are reusable evidence; company-specific motivation remains scoped to its opportunity. Neither a posting requirement nor a derived class-completion status establishes proficiency. Private eligibility remains separate. The optimizer consumes newly approved evidence without silently running another paid Profile comparison.

## Sources and exact documents

Resume uses the confirmed master Profile, including education, courses, individual skills, projects and reviewed Supporting Details. Cover Letter uses its exact selected saved resume plus a bounded, source-owned snapshot of confirmed professional Profile evidence captured by an explicit full optimization. Later source changes cannot alter saved letters; source changes detected during generation reject late output. Before a partial or local revision, used additional Profile sources must retain their original ownership, dates and permitted attribution. Changed permissions require explicit full optimization even when the source quote is unchanged; no partial writer request is sent. Used-source metadata and the captured evidence version are checked again inside the revision commit transaction, closing changes during writer/audit/reviewer waits without another provider call.

New tailored resumes use a versioned, single-column US Letter layout: Arial 10.5-point body, 12-point bold uppercase section headings, 19-point bold name, centered contact/headline, fixed .6-inch side and .48-inch top/bottom margins. Dates appear at the right text margin using tab stops; known numeric months expand to full month names without inventing missing dates. Skills and Certifications remain separate. Content selection/wording must fit one page; font size is not reduced to force a fit. Old rendered files retain their original layout. Cover Letter uses the existing readable one-page letter renderer.

Downloads at the bottom finalize the exact acknowledged revision, without navigation or another AI request. Save & Continue chooses that immutable document for the following step. Resume upload/local building alternatives remain available below the workspace. Skip Cover Letter at the top opens Finish and preserves the letter history.

## Recovery and interfaces

- GET/PUT `/api/document-models`: account-owned `writer` and `reviewer` model/reasoning/speed choices. Requires authentication; writes require the existing CSRF controls. `SettingsUpdate.document_models` is additive for backup compatibility.
- GET `/api/document-models/tasks/status?request_token=...`: returns only the current account's matching document task ID/status. It does not dispatch provider work.
- GuidedBuild adds optional `skip_questions` and `request_token`; conversation messages and fact approvals add optional request tokens. Existing clients remain parse-compatible.
- POST `/api/cover-workspaces/{id}/quality-review`: existing exact-revision/version/token request shape, with immutable cover-review revisions.
- Conversations retain optional `optimization_waiting`; revisions retain exact-document quality results, role usage and cover professional-source snapshots. No SQL migration is needed.

The client persists account/workspace-scoped pending tokens. A lost start or disconnected polling recovers the original task and payload; successful reload recovery clears its pending marker. Terminal failure/cancellation clears it so a later explicit retry can use a fresh token. Server-side task-token deduplication and active-workspace guards prevent concurrent document actions from initiating duplicate paid work. Progress shows stages, elapsed time, Stop and unknown-status recovery.

## Verification boundaries

All implementation checks use fictional data and mocked provider responses in network-disabled containers. Browser checks cover desktop widths 1280/1600/1920. These checks establish app orchestration and rendering, not live-provider entitlement or real-world writing quality. Production-account AI calls and mobile checks are not part of verification. Publication/deployment requires the round's combined Profile integration review and fresh exact-candidate clearance; installed localhost stays unchanged.
