# Job Search and daily alerts

Search supports Greenhouse, Ashby and Lever employer boards, Adzuna, and USAJOBS. Employer feeds cover only the employers added to the account. LinkedIn and Handshake open their own websites; they are not scanned automatically. Indeed and the former JobSpy scraper are excluded from new searches. AI web expansion is a separate manual, paid action; daily alerts never call a model.

## Account and shared connections

Adzuna is configured in **Settings → Job search connections** for each account. Its ID and key are encrypted in a separate account-bound provider store. They are never returned to the browser, included in ordinary account exports, or resolved from another user's account. Environment-based Adzuna fallback is retired. **Test only** is the default; it excludes the connection from manual and daily searches. The explicit test button uses exactly one small API request. Saving, migration and removal make no provider calls. Confirm your provider plan before enabling regular searches; no paid upgrade is performed.

Configure these shared services through the installation's protected environment file; never place secrets in public source files or chat:
- `USAJOBS_API_KEY`, `USAJOBS_API_EMAIL`: request access at https://developer.usajobs.gov/apirequest/index . The email must be the address registered for that API key, not each job seeker's address.
- `CF_EMAIL_TOKEN`, `CF_EMAIL_ACCOUNT_ID`, `ALERT_FROM`: optional Cloudflare email delivery. Configure the sender for this local installation. Use a dedicated, narrowly scoped token supporting Email Sending and reading/creating verified Email Routing destination addresses. Do not reuse the tunnel or broad administrative token in the app.

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

The nearest upcoming reviewed expected graduation selects an initial job type: within nine calendar months (inclusive) selects early-career full-time roles; farther away selects internships. Older completed degrees do not override a current dated program. Completed education without a current undated program defaults to full-time roles. Missing or ambiguous dates select both. Month/year precision is treated as a range; the app never invents a graduation day. Calculations use the saved browser-detected time zone. Manually changing job-type checkboxes persists an override. **Use Profile default** restores automatic behavior. Previously saved selections migrate as manual choices.

A shared curated catalog supplies field bundles, deterministic Profile suggestions (up to four), and search aliases. Suggestions inspect only selected professional fields of confirmed Profile records, make no AI requests, and never select themselves or claim qualification. Bundles add to existing choices; an addition exceeding 12 roles is rejected without partially adding anything. LinkedIn and Handshake stay visible, Posting date sits beside Location, and Work arrangement is in Search options. Disabled Search and AI expansion buttons explain the missing prerequisites inline. AI expansion requires the account's own OpenAI key and enabled web search.

Search caches include the matching catalog version and account provider-connection revision. Removing/replacing a connection invalidates reuse of earlier provider results. Daily runs re-resolve the owning account's connection and skip test-only Adzuna credentials. Installation recovery requires the matching database and protected encryption key; ordinary account exports deliberately cannot transfer provider credentials.
