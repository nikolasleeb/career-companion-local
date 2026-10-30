# Interview guides and saved practice

The Interview Practice landing page offers six formats and saved sessions. Behavioral includes STAR as an answer structure. Coding retains its existing setup. Other formats open bundled editorial guides without creating records or requesting AI.

The first catalog contains 33 original questions: Behavioral 10, Case/business 6, Domain/scenario 7 (one per broad career field), Presentation/portfolio 6 and Other 4. General structures remain visible; individual approaches expand on each card. The sources support methods and formats, not the fictional cases or a claim about question frequency. No proprietary question bank is reproduced.

`GET /api/interview-practice/guides` requires an authenticated account and returns the versioned catalog, source links and review date. It does not require an AI key. The versioned JSON lives under `backend/app/data/interview_guides.json`; IDs are stable when wording is maintained. Changes require manual source review.

`POST /api/interview-practice/sessions` additionally accepts optional `guide_question_id`. Unknown IDs and type mismatches return 422 without saving anything. The session and guide question are committed in one transaction, with ownership of context records rechecked under the write lock. The response remains the saved session; its question is retrieved through the existing session detail API. Source prompt and provenance are snapshots, with `origin: guide`. Editorial provenance is not a Profile evidence citation or automatically supplied answer.

Routes reuse `tab` (`behavioral`, `case`, `domain`, `presentation`, `other`, or `coding`); the suffix `-setup` opens non-coding setup. `topic` contains only a stable starter question ID. Existing `item` and `question` session routes are unchanged. Unknown starters require choosing a different question or explicitly starting without one. Setup drafts stay in account-scoped browser storage. No private text enters URLs.

A guide question is immediately available for Typed, Voice or Mixed answers. Guide browsing, setup and saving the starter make no AI calls. Generation, feedback, follow-up, audio processing and narration remain separate explicit AI actions. Work Styles consent is still off for new sessions. Existing STAR sessions retain `kind: star`, their structured-answer default and original content.

Verification uses fictional desktop accounts and simulated AI, including account isolation, atomic rollback, older STAR sessions, guide navigation, setup preservation, backup/restore and deletion. No paid user-account requests or mobile checks are needed.

Behavioral additionally supplies ordered `further_reading_ids` referencing the shared source catalog. Its three public links are visible below the questions, open in a new tab, and are omitted from the collapsed source list to avoid repetition. Source `access_note` is optional and shown with further reading; the U of A note distinguishes its public guide from NetID access to Big Interview. Other formats retain their existing source lists. The reading catalog changes no saved question IDs, destinations or original provenance snapshots.
