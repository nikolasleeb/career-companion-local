# Job Search sources

The bundled catalog contains 100 curated employers across industries, not a
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

Public feed snapshots use a six-hour cache and six concurrent source fetches.
Failed refreshes preserve the last successful snapshot and timestamp. Snapshots
older than 48 hours are marked stale and excluded from new-job alerts. Each new
successful source establishes an account alert baseline. Results are limited to
500 matches, balanced across sources and employers, and displayed 25 per page.
Clearly senior/supervisory roles and known foreign locations are excluded;
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
