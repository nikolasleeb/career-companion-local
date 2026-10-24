# Career Companion Local 1.0.7

Simpler Application Assistant, with extension 1.0.3:

- Applications load automatically and account-scoped document selections survive popup reopen. Sharing requires approval of the exact saved versions.
- One primary button handles Start filling, Review questions, Resume filling and Finished. Stay on the employer tab; the popup can be closed. After reviewing questions in Career Companion, click Resume filling once in the extension.
- Live status refreshes every second, with readback-verified fill totals, pending questions and last successful contact. Requests time out after 15 seconds with actionable login, validation or connection errors.
- Saved inactive runs require explicit recovery. Reconnection can recover a paused run only on its original tab and origin, with unchanged approved documents. Routine filling makes no model calls and never submits an application.
- Individual uploads, custom controls and protected confirmations stay manual while unrelated supported fields can fill. Hard login, CAPTCHA, payment and frame boundaries remain stops; legacy scans retain conservative behavior.

Resume fixes since 1.0.6:

- Include confirmed education header dates in source verification.
- Shorten actual wrapped wording to fit one page while preserving readable typography and selected certifications. Verify the resulting PDF before claiming one-page success.
- Improve the Progress & history layout and first-use instructions.

Update/reload the extension once after replacing its unpacked folder. Reconnect if the browser cleared its session. Back up both Docker volumes before updating the app. Chrome package behavior was tested on fictional forms; the Safari source package shares the core but is not a signed Safari installation.
