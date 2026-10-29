# Career Goals: overall direction and specific milestones

Profile → Career Goals has three sections: **Overall career direction · One statement**, **Specific goals · Optional milestones**, and **Use Career Goals for AI guidance**.

## Write an overall statement

Create one optional statement using the guided fields. Choose Yes, No or Skip education for “Are you currently pursuing a degree?” This choice controls prompts only and never edits verified Profile education. Students can supply their graduation date and degree; other users can optionally describe completed or future education. Everyone can add desired work, skills, certifications, timing, commitments, priorities and other context.

Leave any field empty or enter exactly `[blank]` to omit it. Switching education paths keeps entered fields available when you switch back, but hidden education fields are excluded from the preview. Punctuation-only entries do not generate a statement. Sentence assembly and saving are local and use no AI.

Choose **Edit statement directly** to review your own wording. Direct edits stop automatic sentence replacement. **Rebuild from guided fields** asks before replacing the draft with generated prose; the saved statement changes only after Save. Existing statements always open in direct mode without rewriting. Cancel discards the open editor, not the saved statement. Failed or stale saves keep the current draft; Load latest saved goals refreshes the saved revision before an intentional retry.

## Track individual goals

Specific goals remain independent milestones with categories, optional dates, priorities, progress and linked occupations. Overall direction is no longer a category in the specific-goal form. It has its own Create, Edit and Delete actions. Deleting the overall statement leaves milestones and historical conversations intact.

## AI context and consent

The existing sharing choice is preserved, off by default for new accounts. When enabled, guidance uses labeled overall-direction and milestone text as aspirations. Guided-editor fields are excluded from provider payloads; the statement is sent once rather than repeated in note, items and editor fields. Guidance connects relevant milestones without treating future skills/certifications as qualifications and asks about contradictory dates/priorities.

Career Plans can explicitly include selected direction/milestones even when automatic sharing is off. Cover letters and application motivation retain their separate explicit selection and review rules. Existing conversations/plans/documents retain their snapshots. Saving goals does not itself launch generation or rewrite employer documents.

## Compatibility

`GET/PUT /api/profile/career-goals` retains account ownership, expected revisions, stable IDs, at most one `general_statement`, and at most 30 specific goals. Its display name is Overall career direction. The optional `guided_editor` object has `version: 1`, `mode: guided|direct`, `education: yes|no|skip`, and validated bounded `fields`. Canonical reviewed `text` remains authoritative. The existing entity storage needs no table migration.

Legacy text-only statements remain supported. A text-only replacement or item replacement without editor metadata clears prior editing aids. Backups/imports validate and preserve the optional editor object. Guided data is not professional evidence or a search-index qualification.
