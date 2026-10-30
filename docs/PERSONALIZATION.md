# Profile personalization

Profile → Personalization controls automatic professional Profile, Career Goals and reviewed Work Styles summary context. Saving is explicit and revision checked. Until the first save, existing feature opt-outs remain effective. Updating a summary or goal does not change sharing permission.

## Context contract

- `profile_context` projects confirmed account-owned records and valid project/job/education/course links. Relationships supply context and never create duplicate accomplishments.
- Supporting Details require valid confirmed destinations and retain version, exact excerpts and provenance. Orphaned and unlinked details remain stored but are excluded from new evidence.
- Selection happens locally before provider dispatch. Long fields remain searchable. Source IDs and compact relationships travel with selected facts; context-only metadata cannot establish job qualifications.
- Work Styles supplies a reviewed summary only to ordinary consumers. Raw questionnaire answers and assessment reports/scores stay out of general Coach, job matching and document generation.
- Automatic guidance follows the Profile setting. Explicit task inputs and document evidence retain their scope. Coding exercises omit Work Styles. Resource browsing requires no AI request.
- Resume posting comparison retains citizenship, authorization and sponsorship settings for eligibility checks only. Other private application answers remain within application filling; no disclosure-vault access was added to AI guidance.
- Relationship, confirmation and permission changes affect revisions. Responses recheck source eligibility and relevant revisions after provider waits. Historical reviews and saved document snapshots are not rewritten.
- Backup restoration remaps links and keeps a restored personalization choice disabled when the target account has no prior choice. It never silently enables sharing or replaces an existing account's choice.

## Verification

`backend/tests/test_personalization.py` uses fictional accounts and simulated providers. Existing consumer tests cover Coach, planning, career connections, interviews, Skills, job matching, application help and document builders. No test requires a live paid account key. Desktop interface checks include keyboard toggling, save/reopen, failure recovery and stale-tab conflicts.

The public/local edition retains its existing guide capabilities. The hosted writing-guide Coach additionally follows this setting once saved; before that, existing guide selections remain effective. Publishing source does not update an installed localhost service.
