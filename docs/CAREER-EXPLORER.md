# Career Explorer

Resources → **Career Explorer** has **Explore careers**, **My saved careers** and **Saved searches**.
It is available to signed-in accounts before Profile setup is complete. The
existing Career Plans, Skills and Interview Practice remain separate. Work Styles lives under Profile.
No AI, O*NET key, external request or questionnaire score is needed to browse.

## Public data and attribution

The bundled `backend/app/career_explorer_data.json` contains 1,016 O*NET 31.0
occupations, complete descriptions, alternate titles, related occupations, skill
importance and technology examples. Education links use the O*NET-SOC 2019 / 2020
CIP crosswalk. Original source attribution and CC BY 4.0 links are retained in
the data and displayed in the app. The dataset is a derivative, not an endorsed
O*NET matching instrument.

The original BLS snapshot supplies 2025–2035 projections for 377 college-preparation occupations. The new OEWS dataset supplies published pay distributions across preparation levels and salary areas, with source geography and year attached. Missing information remains null or its published suppression marker, never zero. Growth and annual openings remain projections rather than live vacancies.

`scripts/build_career_explorer.py SOURCE_ZIP` deterministically rebuilds the
snapshot from the reviewed public files in the supplied teammate archive. It
reads known CSV/JSON members only and executes no archived code. The resulting
metadata records the source archive SHA-256 and preparation date. Retain original
O*NET attribution when updating. Future refreshes must validate source years,
SOC mappings, missingness and licensing before replacement; no scheduled refresh
or paid embedding rebuild is enabled.

## Matching and privacy

Study exploration links entered majors/courses to at most three matching CIP
programs per input, then to occupations and their close relatives. Exact major
links come first, followed by their close relatives, broader major links, their
relatives and course-only links. Common GIS,
HR, IT, MIS, CS and CIS abbreviations are expanded for program matching. Links
are possibilities, not proof of qualifications. Unmatched studies show an
explanation and the option to browse other directions. Users can choose title,
pay or growth ordering instead of relevance. Unknown numeric values sort last.

Only confirmed education supplies initial major suggestions. A responsive four-,
three-, two- or one-column course picker loads confirmed education lists and
standalone coursework records. It merges duplicate course names, shows their
Profile sources and starts with none selected. Select all / Clear selection apply
only to Profile courses. A separate field accepts other subjects to explore.

Selected course IDs are account-scoped and resolved from the current confirmed
Profile on each study search; deleted or unconfirmed selections produce a conflict
instead of silently using stale facts. The existing free-text course field remains
compatible. Profile selection is independent of its 2,000-character limit. Course
listings are not proof of completion.

Users can edit temporary search fields without changing Profile. Confirmed professional evidence is compared using established aliases and contextual passages. The evidence, AI-review and Work Styles consent boundaries are described below. Saved careers and review findings never become Profile evidence automatically.

## Saving and connections

Accounts can save up to 50 careers. Saves are transactionally deduplicated by
occupation code, isolated by account and included in ordinary account backups.
Restores are additive and deduplicate existing bookmarks; historical codes remain
preserved and display as unavailable when absent from the current catalog.

- **Add as Career Goal** explicitly saves an aspiration through the existing
  revision-checked goals interface; AI guidance consent remains unchanged.
- **Find jobs in this occupation** fills the normal Job Search form and preserves
  its other filters. It never starts a search or paid action automatically.
- **Explore a skills plan** preselects up to three undocumented skill topics for
  review in Skills. Generating a plan remains a separate explicit AI action.
- **Discuss with Career Coach** opens a draft question. It never sends it.
- Those three workspace tools retain their existing Profile-setup requirements.

## Interfaces

Authenticated `/api/career-explorer` endpoints:

- `GET /options`: public metadata, industries and the account's confirmed study
  suggestions.
- `POST /explore`: bounded study/title/industry/preparation filters, explicit sort
  and pagination; no persistent write.
- `GET /occupations/{code}`: attributed facts and conservative Profile skill labels.
- `GET /saved`, `POST /saved` (`code`, `source`), `DELETE /saved/{id}`: account-owned
  bookmarks. Mutations require the standard session and CSRF protection.

The only new persistent entity kind is `saved_career`. No destructive migration,
Career Journey workflow, personality matching, sponsorship ranking or new paid
AI matching is included in this first integration.

# Evidence, wages and rerunnable searches

Exploration, local Profile reference matching and saved-search operations use no AI. A Profile connections review requires an explicit action and an account OpenAI key. It uses the existing task, cancellation, token-limit, cost and request-token mechanisms with paid retries disabled.

Local references come from confirmed professional Profile records and Supporting Details. Coursework and credentials provide learning context. Established aliases identify mentions, not proficiency. Broad activities and contextual relationships are marked for review. Work Styles contributes only the reviewed summary when guidance sharing is enabled; raw answers and scores are excluded from Explorer reviews. Reviews remain separate from Profile and carry source snapshots and revision checks. A failed or cancelled review cannot replace the prior saved result.

## Rebuilding wages

The bundled `backend/app/career_wage_data.json.gz` contains BLS OEWS May 2025 national, state, metropolitan and nonmetropolitan wage distributions. Its metadata records official source URLs, SHA-256 checksums and reference year. BLS data is public domain.

Download the national, state and metro ZIP files linked from <https://www.bls.gov/oes/tables.htm>, then run:

```sh
python3 scripts/build_career_wages.py oesm25nat.zip oesm25st.zip oesm25ma.zip
```

The importer reads cross-industry, all-ownership rows, preserves published suppression/top-code markers, orders keys and sets the gzip timestamp to zero. The same inputs produce the same output. The source ZIP checksums are stored inside the output; no user data is used.

An O*NET specialty maps to its six-digit SOC wage occupation. No specialty-specific distribution is invented. Missing local rows retain a clearly labelled national comparison. The 10th–90th range describes the published wage distribution, not starting pay or years of experience. Annual and hourly distributions retain their units; pay sorting orders published annual figures, then hourly figures, with missing medians last. Published top-codes use their reporting floor for sorting and remain labelled “or more.” The May 2025 reporting thresholds are $239,200/year and $115/hour; see <https://www.bls.gov/oes/methods_25.pdf>.

Saved searches store applied filters and selected course titles. Reopening reruns the current catalog. Unavailable courses or salary areas require review; nothing is silently substituted. Search and review entities are account-owned, included in account exports/imports, and listed under Career Explorer in selective cleanup. Restoration preserves current saved reviews and marks imported reviews outdated.

Work Styles lives in Profile. Legacy `#/work-styles?item=…` links canonicalize to `#/profile?tab=workstyles&item=…`, retaining attempt IDs and the existing account-scoped draft buffers. Moving the workspace grants no additional sharing consent.


## Optional Profile selectors

The course and skill selectors start collapsed and show selection counts. Expanding,
collapsing, selecting all and clearing are local interactions; nothing is selected
automatically. Course selection remains available on the studies route. Skills are
available on either route and come only from explicit `skill_items` in confirmed
Profile records, with source labels. Narrative mentions and self-reflection answers
are not converted into selectable skills.

Selected skills require at least one corresponding published occupational skill or
technology name, using the same established aliases as Explorer evidence (for
example, PowerBI and Microsoft Power BI). Studies and other filters still apply.
Relevance orders title matches, then number of selected-skill connections, then
study connections. Other explicit sort orders are unchanged. Unmatched skill names
are reported, never assigned inferred proficiency. Skill connections appear on
result cards and use no AI or external request.

Saved searches include account-scoped skill IDs and portable title references.
Loading remaps current confirmed choices (including aliases), reports unavailable
skills for review, and does not silently rerun when selections are unavailable.
Backup/import validation and deduplication include these references. Older searches
retain their existing behavior with no skills selected.

Career Plans saved chats expand inline into a compact, searchable list. Choosing a
conversation keeps the existing route and conversation behavior; expanding the list
never sends an AI request.
