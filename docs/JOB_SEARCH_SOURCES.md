# Job Search sources

The bundled catalog contains 298 distinct curated employers across 299 feeds across industries, not a
ranking of the largest employers. Each record includes the career-page URL,
working public Greenhouse, Ashby or Lever feed, identity label, verification date
and number of postings observed. Availability changes over time. Account-added
boards merge by provider, token and region; selections belong to the account.

Candidates came from the [LastRound AI ATS company directory](https://github.com/fyrosofttech/lastroundai-hiring-data/tree/main/ats-directory),
by [LastRound AI](https://www.lastroundai.com/), companion to its
[pay transparency study](https://lastroundai.com/blog/salary-transparency-study-2026), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
We selected records, normalized labels and checked their identities, career pages
and live feeds. The directory's license does not license employer job postings.
Full verification metadata and attribution are in `backend/app/employer_catalog.json`.

The optional GitHub source reads factual metadata from
[ConorsCode/open-jobs-data](https://github.com/ConorsCode/open-jobs-data), including
employer apply links, source posting dates where present, scrape timestamps and
the snapshot timestamp. Its MIT code license does not confer rights to employer
postings. No repository code or workflows are downloaded or executed. Descriptions
are not mirrored. Location, inferred remote labels and requirements need review.
Simplify's internship and new-grad repositories are linked, not mirrored.

Public feed snapshots use a six-hour cache and six concurrent source fetches. The employer-feed phase has a 180-second budget. It retains completed results and marks unchecked/timed-out feeds as incomplete coverage; their missing results never mean no vacancies. Custom selections accept up to 1,000 feed identifiers, including saved preferences and backup imports.
Failed refreshes preserve the last successful snapshot and timestamp. Snapshots
older than 48 hours are marked stale and excluded from new-job alerts. Each new
successful source establishes an account alert baseline. All fetched matching listings are retained, balanced across sources and employers.
Server-side pages offer 25, 50 or 100 jobs; result keyword filtering is free and
searches the retained set, including descriptions. Provider pagination is still bounded.
Clearly senior/executive roles and known foreign locations are excluded;
unknown requirements remain available under Needs review. This is not a complete
index of the job market or proof of employer intent to hire.

## Adzuna privacy and manual trial

Adzuna credentials are encrypted per account, separately from OpenAI credentials,
never returned or exported. There is no installation-key fallback. Regular
connections use only their owner's credentials. The hosted pilot owner may choose
Manual trial without replacing their key. This is an explicit operator allowlist,
not a permission inherited by other accounts or the public localhost edition.

Manual trials use the first two selected roles by default, or up to two chosen
under Search options. Each role uses one request for page one, at most 25 results.
There is no automatic retry or pagination. A failure stops the trial source and
retains other results. Account-scoped task tokens and durable pre-request claims
prevent duplicate attempts; crashes do not retry a claimed call automatically.
Cache hits make no calls. Recorded attempt counts cover this installation's new
manual requests, not historical or external use or exact remaining allowance.
Trial results and credentials never enter the public snapshot cache. Scheduled
checks remove trial connections before discovery; trial results are never used
as a source for daily alerts. Normal searches use no AI.

The trial is limited evaluation access. Provider terms and appropriate licensing
still apply; no paid upgrade is made automatically. Adzuna redirect URLs and
attribution are retained. Its snippets are incomplete and require a full posting
review before tailoring.

## Employer industries and listing timers

The latest 2026-10-28 expansion retains all 143 previous feeds and adds 156 verified feeds. Each industry now has at least 40 distinct employers. See [coverage verification](EMPLOYER_COVERAGE.md). The catalog covers Science & research, Healthcare & life sciences, Education, Finance & professional services, Manufacturing & engineering, Climate & energy, Nonprofits & public interest, and Consumer services & logistics. Technology remains a separate preset. Public feed/platform coverage varies by sector; this is not a complete employer index. Zero current postings can still be a working feed. Verification dates and observed counts describe the check, not future availability.

Industry presets select employer feeds, while role and location filters select jobs inside them. Presets resolve at search time, so matching catalog additions join later searches. All employers remains the default. Selecting individuals switches to Custom; previous explicit selections are preserved. Manual searches, daily checks, For You and Ask AI use the same saved source choices. USAJOBS and Adzuna are independently selectable.

**Listing availability window — 30 days:** Current listings expire 30 days after their last source confirmation, or sooner if closed. A new source confirmation extends this window. Applications and their documents remain saved.

**Reuse public feed results — 6 hours:** Searches and scheduled checks may reuse a downloaded public employer/community feed for six hours before fetching it again. Explicit Refresh can request an earlier update. These settings describe cache reuse and confirmed availability, separately from the selected posting-date window.
