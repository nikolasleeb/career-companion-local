# Chunk 2 validation and review

Chunk 2 reorganizes Profile and application editing while retaining Chunk 1 personalization payloads and backend APIs. No database migration is included.

## Delivered behavior

- Personalization is the final Profile tab, with direct links, keyboard navigation, remembered selection and explicit save. Resume, letter and eligibility explanations are separate.
- Profile review counts route to pending imports, unconfirmed records, Supporting Details and unresolved relationships without approving anything automatically.
- In-site confirmations and text dialogs replace native app prompts in Profile, application documents and Coach. Browser unload warnings remain native.
- Profile record editors, panels, material sessions and document editors remain mounted during navigation. Failed saves and revision conflicts retain drafts. Actions discarding work require confirmation.
- General Coach keeps separate unsent drafts for each conversation and remains separate from document discussion. Modals suspend Coach; closing Coach restores the document message draft. Document fields remain editable.
- Applications lead with status, dates and deterministic next actions. Documents contains files/versions; Activity contains status/interview history.
- Documents follow Posting, Resume, Letter and Finish. Letters use the exact selected saved resume. Missing versions require explicit selection. Letter skipping is explicit. Nothing submits automatically.
- Project materials follow Add materials, Analyze, Review and Approve. Opening/adding/reviewing does not analyze. Findings remain separate from personal contributions.

## Verification

- Hosted frontend: 279 tests passing. Public frontend: 280 tests passing. Both production builds pass.
- Hosted backend: 1,339 tests passing, one skipped. Public backend: 159 focused tests passing for personalization, imports, materials, recovery and documents. Providers are simulated.
- Fictional desktop accounts at 1600 and 1280 pixels exercise tab navigation, failed saves, stale revisions, mounted drafts, confirmation Escape/safe focus, material reopening, handoff collisions, modal suspension, document discussion preservation, cancelled back navigation, exact-version continuity, missing versions and PDF/DOCX/TXT export.
- No paid user-account requests or mobile tests. Public source audit checks credentials, runtime data and personal home paths.
- Backend source and AI access behavior remain unchanged. Existing snapshots, relationships, confirmation gates, Supporting Details and bullet editors remain intact.

## User review

1. Try Profile Personalization and switch tabs with an unsaved choice.
2. Follow a review-queue link; edit and cancel without losing text.
3. Open project materials, add or paste content, close and reopen. Choose Analyze only when desired; approve your own contribution separately.
4. Move an application through Posting, Resume, Letter and Finish. Check the exact resume version, explicit letter skip, Documents and Activity.
5. Type a document message, open and close general Coach, and verify that the document message returns.

Chunk 3 requires separate approval. Installed localhost is not updated.
