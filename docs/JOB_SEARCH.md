# Job Search and daily alerts

Search supports Greenhouse, Ashby and Lever employer boards, Adzuna, and USAJOBS. Employer feeds cover only the employers added to the account. LinkedIn and Handshake open their own websites; they are not scanned automatically. Indeed and the former JobSpy scraper are excluded from new searches. Ask AI is a separate manual, paid action; daily alerts never call a model.

## Account and shared connections

Adzuna is configured in **Settings → Job search connections** for each account. Its ID and key are encrypted in a separate account-bound provider store. They are never returned to the browser, included in ordinary account exports, or resolved from another user's account. Environment-based Adzuna fallback is retired. **Test only** is the default; it excludes the connection from manual and daily searches. The explicit test button uses exactly one small API request. Saving, migration and removal make no provider calls. Confirm your provider plan before enabling regular searches; no paid upgrade is performed.

Configure these shared services through the installation's protected environment file; never place secrets in public source files or chat:
- `USAJOBS_API_KEY`, `USAJOBS_API_EMAIL`: request access at https://developer.usajobs.gov/apirequest/index . The email must be the address registered for that API key, not each job seeker's address.
- `CF_EMAIL_TOKEN`, `CF_EMAIL_ACCOUNT_ID`, `ALERT_FROM`: optional Cloudflare email delivery. The hosted sender is `jobs@notify.austrich-server.com`; local distributions must configure their own sender. Use a dedicated, narrowly scoped token supporting Email Sending and reading/creating verified Email Routing destination addresses. Do not reuse the tunnel or broad administrative token in the app.

The compose files pass shared service variables into the app. Recreate only the app service after changing its protected environment. Provider credentials are not included in account exports or browser capabilities. Missing connections show actionable setup messages and do not block other sources.

## Sender setup without a mailbox

Cloudflare can send from an onboarded domain/subdomain without an inbox or personal email login. Configure sender DNS under the notification subdomain and verify it with Cloudflare. Preserve existing website, Access and mail records. A dedicated sending token is needed; the existing tunnel credentials do not establish email access.

The initial implementation sends only to provider-verified recipients. Cloudflare documents free sending to verified destinations, subject to its current product conditions. No paid upgrade is performed. Sending to arbitrary recipients requires a different plan/setup and is outside this rollout. Users request recipient verification, complete Cloudflare's verification if necessary, then request and confirm an account-bound six-digit code. A recipient cannot be enabled merely because another account verified it.

No email is sent until a user explicitly requests verification or enables email alerts. Digests contain public job information, not resumes, private eligibility answers or application documents. Email settings links lead back to the protected website and require sign-in; they do not bypass Cloudflare Access. Disable email in Daily alerts to unsubscribe.

## Browser notifications

Choose Enable on this browser, grant the browser's notification permission, then save the daily alert settings. Web Push uses a service worker with no fetch handler and caches no account content. Messages contain a generic count and link; clicking opens the protected Job Search page. Browser/OS support and settings determine delivery when tabs are closed. No installed app or extension is required. Enrollment is account-scoped; unenroll a shared browser before connecting another account.

## Scheduling and recovery

Daily alerts are initially off. Each account has one daily schedule, defaulting to 08:00 in the browser's detected IANA time zone. The server must remain awake and the app container running. A persistent unique run per account/local date prevents duplicate scans; after downtime the next tick does one catch-up run. The initial successful check for each source establishes a baseline without sending all existing jobs as new. Changing saved search preferences establishes a fresh baseline. Failed sources do not advance their baseline.

Searches and provider pagination are bounded. A failed or capped source does not mean no jobs exist. The daily history shows source coverage and delivery status. Newly found means not previously seen by this alert, not proof of the employer's original posting date. Date fields distinguish publication, republication, aggregator listing and discovery. No salary, citizenship or degree eligibility is inferred.

Delivery intent is persisted before contacting a provider. An interrupted or uncertain send is not automatically replayed, because the recipient might already have received it. This favors avoiding duplicates and reports an unconfirmed outcome honestly. Expired browser subscriptions are removed. Provider failures do not turn off website results.

Account backups preserve preferences, saved/dismissed jobs, and schedules. Imports pause restored schedules and require renewed channel verification; push endpoints and private provider credentials are never imported. Keep protected installation backups of the database, uploads, credentials and the secrets volume, including the persistent `job-push.pem` signing key, for service recovery.

## Search preferences

Roles use a searchable multi-select picker. Choose suggestions from any discipline or type a custom role and press Enter. Selected roles, previously added custom choices, location and filters save automatically to the signed-in account, without starting a search or an AI request. Removed choices remain available in the picker for reuse. The picker supports up to 12 selected roles. Failed saves show Retry save.

Location accepts city/state names, state abbreviations, or named regions such as East Coast. Each region displays its included states. USAJOBS receives explicit state names for regional searches; employer feeds use their posting locations for matching. Known outside-region listings are excluded, while location-unknown listings remain marked Needs review. Full state names and abbreviations match consistently; a company-office mention in description text never establishes the work location.

## Education-first access and role defaults

One reviewed education entry with a school and degree/program unlocks workspace features immediately. Other Profile sections, dates, GPA, major and uploads are optional. Legacy completion flags do not bypass this check. Removing the last qualifying education entry returns the account to Profile without deleting saved work. Account settings, Profile editing/review/import, backup/restore and sign-in remain available. Unreviewed optional records stay drafts and do not become resume evidence automatically.

The nearest upcoming reviewed expected graduation selects an initial job type: within nine calendar months (inclusive) selects early-career full-time roles; farther away selects internships. Older completed degrees do not override a current dated program. Completed education without a current undated program defaults to full-time roles. Missing or ambiguous dates select both. Month/year precision is treated as a range; the app never invents a graduation day. Calculations use the saved browser-detected time zone. Manually changing career-level buttons persists an override. **Use Profile default** restores automatic behavior. Previously saved selections migrate as manual choices.

A shared curated catalog supplies field bundles, deterministic Profile suggestions (up to four), and search aliases. Suggestions inspect only selected professional fields of confirmed Profile records, make no AI requests, and never select themselves or claim qualification. Bundles add to existing choices; an addition exceeding 12 roles is rejected without partially adding anything. LinkedIn and Handshake stay visible, Posting date sits beside Location, and Work arrangement is in Search options. Disabled Search and Ask AI controls explain the missing prerequisites inline. AI discovery requires the account's own OpenAI key and enabled web search.

Search caches include the matching catalog version and account provider-connection revision. Removing/replacing a connection invalidates reuse of earlier provider results. Daily runs re-resolve the owning account's connection and skip test-only Adzuna credentials. Installation recovery requires the matching database and protected encryption key; ordinary account exports deliberately cannot transfer provider credentials.

## Paging, career levels and Ask AI

Search, Ask AI, Saved jobs and Daily alerts have separate tabs. Internship, Early career and Mid career are multi-select buttons. Four years of reviewed relevant professional employment selects Mid career automatically; overlapping periods count once, internships are excluded and imprecise dates use conservative bounds. No age or degree-level inference is used. Otherwise graduation defaults apply. Manual overrides continue to take priority.

All fetched matches are retained, with account-saved page sizes of 25, 50 or 100. Keyword search checks all retained titles, employers, locations and descriptions without provider or model calls. Confirmed filter matches and uncertain hard requirements have separate views. Missing pay without a pay filter is ordinary missing information. Known location or salary conflicts are excluded. Older capped searches cannot recover discarded listings without a fresh search. Alternate known ATS URLs share one identity; distinct requisitions stay separate. Existing application references and uploaded originals are preserved.

Ask AI accepts a natural-language job request and up to four optional PDF examples (10 MB, 30 pages each). Uploaded originals remain account-owned; examples never become applicant facts, Profile imports or applications. Unreadable PDFs need replacement or pasted text; automatic OCR is not promised. Explicit instructions override examples; omitted location, date and career filters inherit saved preferences. Pay minima require an explicit request with resolvable units.

Find jobs first uses the account's own OpenAI key and current model/reasoning/speed. Then a local estimate shows the actual candidate count before a separate paid Profile review. Quick review screens all available candidates and deeply reviews the strongest 25; Detailed reviews every candidate. Dismissed jobs are excluded. Comparing saved results does not rerun discovery or Adzuna. Reviews use confirmed professional evidence only, with checked Profile/posting quotations, gaps and unknowns, ordinal fit labels and explicit screened/detailed/limited scope. Labels are not hiring probabilities. Public web queries receive role criteria, not the raw Profile.

Each paid batch is checkpointed before submission and after validated completion. Cancellation stops before the next request; already-sent requests may incur usage. Restarted/failed reviews retain completed batches and require explicit resume. Unknown in-flight responses are never silently replayed. The browser retains an account-scoped token and input fingerprint for uncertain start responses; checking saved status makes no new AI call. Profile changes mark saved reviews stale and never trigger paid reruns. Imported assessments are read-only; new comparisons use the receiving account's current reviewed Profile. Daily checks use no AI and exclude manual-trial Adzuna.

Search snapshots, example originals and assessments are included in private account backups, with credentials excluded. The paginated result and lazy-detail APIs avoid repeating large posting descriptions in workspace responses. Backup imports accept up to 256 MB to accommodate examples and larger result sets.

## Posting-date window

Choose Past 7, 14, 30, 60 or 90 days; the default is 30. Saved preferences, daily alerts and personalized discovery use the selected window. This is posting age, not cache retention: hosted disposable cache still expires 30 days after source verification, and earlier closing dates still take priority. Sources and request limits can restrict historical coverage.
