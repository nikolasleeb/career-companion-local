# Career Explorer

Resources → **Career Explorer** has **Explore careers** and **My saved careers**.
It is available to signed-in accounts before Profile setup is complete. The
existing Career Plans, Skills, Work Styles and Interview Practice remain separate.
No AI, O*NET key, external request or questionnaire score is needed to browse.

## Public data and attribution

The bundled `backend/app/career_explorer_data.json` contains 1,016 O*NET 31.0
occupations, complete descriptions, alternate titles, related occupations, skill
importance and technology examples. Education links use the O*NET-SOC 2019 / 2020
CIP crosswalk. Original source attribution and CC BY 4.0 links are retained in
the data and displayed in the app. The dataset is a derivative, not an endorsed
O*NET matching instrument.

The teammate's BLS snapshot covers 378 occupations in preparation zones 4–5:
361 have wage data and 377 have 2025–2035 projections. Wage years and broader
occupation-group notes stay attached to each figure. Missing information remains
null, never zero. National medians are not starting salaries, and projected
annual openings are not live vacancies. This is one projection vintage, not a
history of changing forecasts. Other preparation levels remain searchable but
do not acquire invented pay or outlook figures.

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

Only confirmed education supplies initial major suggestions. Users can edit
these temporary fields without changing Profile. Skill labels compare exact
normalized names against skill items in confirmed Profile records; absence means
**Not documented in Profile**, not that the person lacks the skill. Personality
ratings, raw questionnaire answers, inferred/template skills, private disclosures
and sponsorship information are not inputs. Saved careers are not automatically
added to AI context or resume evidence.

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
