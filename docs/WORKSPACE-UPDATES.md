# Workspace update notices

Signed-in pages check the running server build on load and every three hours while visible. A hidden page checks on return only if the interval has elapsed. These are read-only checks and make no AI calls.

When the server build differs from the loaded page, a banner appears at the top with Reload now and Dismiss. Save edits before reloading; the app never reloads automatically. Dismissal is remembered for that update and account in browser session storage. A different update can show a new notice.

Build identity is derived from the bundled client, server and catalog sources, not a container restart or user data. The authenticated version response cannot be cached. Authentication/network errors do not falsely announce updates. Fresh HTML revalidates when reloaded.

A page loaded before this feature was installed needs one manual reload to receive the checker. The feature does not update the installed localhost service by itself or create GitHub releases.
