# Test the expanded employers and simpler account controls

This update adds verified employer feeds and reorganizes Settings. It does not remove any account information automatically. Use a disposable account and fictional applications for deletion tests.

## Employer sources

1. Open **Settings → Job Search → Employer sources**. Expect **298 distinct employers** across 299 feeds. Industry totals are listed below; employers can belong to more than one industry when their work supports it.
2. Select Science & research, then add Healthcare & life sciences. Overlapping employers are selected once. Select All employers to return to the full catalog.
3. Open Choose individual employers and change one checkbox. The selection becomes Custom. Refresh the page to check it stays saved.
4. Run a normal Job Search with the desired industries and supported providers. Inspect source statuses. A large cold scan can stop after three minutes; completed results remain available and unchecked feeds say coverage is incomplete. A feed with zero openings is valid.
5. Daily checks, For You and Ask AI inherit the same employer selection. Daily checks are free; For You and Ask AI require a user-started paid AI request. These were tested with mocked providers during rollout; using your real key may incur costs.

## Saved information

1. Open **Settings → Account & backups**. Manage saved information has five collapsed groups. Groups show saved-item counts; empty groups say Nothing saved and cannot be opened.
2. Open Profile & Career Goals. Select one populated category, collapse it and reopen it. Its checkboxes stay selected, and the heading shows the selection count. Nothing starts selected.
3. Choose Review selected deletion. Read the exact records, shared files retained, dependent files and retained historical-copy warnings. Cancel to leave everything unchanged.
4. For a disposable account only, enter the password and DELETE to confirm. Login, API connections, preferences, welcome dismissal and usage history remain. Deleting education relocks application/job-search actions but leaves Resources open.

## Applications: choose two dates, then an action

1. In the separate **Manage applications** card, enter both From and Through. Missing dates or a Through date before From disable both actions. Both endpoints are included.
2. Archive applications previews only current applications in that range. It shows company, role, status and effective date. Date applied takes precedence; otherwise Date added uses the browser's time zone. Confirm archive only after reviewing. Already archived applications stay unchanged.
3. Restore an archived application in Applications when needed. Settings has no bulk-restoration control.
4. Delete applications previews both current and archived applications in the range. It works independently of the saved-information checkboxes. It lists dependent offers/attachments and preserved shared files. It requires the account password and typed DELETE.
5. Change a date after previewing. The preview disappears and must be requested again. An empty range says no applications match and offers no enabled confirmation.
6. Try this on a narrow mobile window. Dates should stack; the group headings and action controls should remain usable by keyboard.

## Verification and rollback

Deployment runs no cleanup and no paid AI requests. A protected hosted database/files/configuration/vault-key backup and previous Docker image are retained by the operator before replacement. The installed localhost service is unchanged. The audited localhost source is pushed to GitHub without a release or tag. If you want to revert, ask to restore the pre-expansion image first; restoring account data is a separate deliberate action.
