# Skills catalog and practice history

Skills provides deterministic resource browsing and short practice ideas. Action Plans owns saved timelines, milestones and progress; the handoff opens a draft and never submits an AI request.

The reviewed catalog is `backend/app/skills_catalog.json`, version `2026-10-30.2`. It contains 516 concrete skills and 512 distinct learning destinations, counted once by primary field:

| Field | Skills | Learning resources |
| --- | ---: | ---: |
| Tech & Data | 264 | 265 |
| Business & Consulting | 46 | 46 |
| Engineering | 55 | 55 |
| Health & Medical | 34 | 34 |
| Education & Public Service | 35 | 34 |
| Arts & Communication | 46 | 44 |
| Science & Research | 36 | 34 |

Legacy support and credential directories remain separate and do not inflate these totals. Generic provider landing pages are excluded from catalog coverage. Stable resource IDs survive canonical redirects; old links and string topic labels remain accepted. Spark, PySpark, Spark SQL and Structured Streaming are distinct connected skills.

## Review and refresh

`scripts/catalog/sources.json` records selected concrete pages, providers, topic labels and subcategories. `technical.txt` is the technical source seed. `source_checks.json` records fetched destination/title/content checks. `web_checks.json` records checks completed through web retrieval where the publisher blocked bulk HTTP retrieval. Review dates are UTC. HTTP success establishes availability, not quality, certification eligibility or continuing free access. Unknown published difficulty is explicitly `Not specified`.

Run `python3 scripts/catalog/check_sources.py` to refresh HTTP checks (public network access required), inspect failures and changed destinations, then `python3 scripts/catalog/build_catalog.py`. Do not mark failed/blocked checks valid without inspecting the actual page through another supported retrieval method. Add aliases only when the terms are equivalent; related skills remain separate IDs. The builder excludes unverified pages and deduplicates canonical destinations. Run `backend/tests/test_skills_catalog.py` after edits. Clinical references are educational materials; they do not grant authority to perform clinical procedures.

## Authenticated API

- `GET /api/skills/options`: compatible suggestions/resources; `include_resources=false` for the paginated UI.
- `GET /api/skills/taxonomy`: version, groups, enums and counts.
- `GET /api/skills/topics`: field, group, source, q, sort, offset; 24 per page.
- `GET /api/skills/topics/{id-or-alias}`: description and related skills.
- `GET /api/skills/resources`: topic IDs/aliases separated by `|`, field/provider/format/access/level/q/sort, offset; 12 per page. Explicit direct and related match labels.
- `GET /api/skills/practice`: newest set for the target containing all selected topics; remaining sets are paginated history with target/topic/date labels. Legacy strings resolve on read without modifying content.
- `DELETE /api/skills/practice/{id}`: account-owned deletion, protected against any queued/running/cancelling preparation task. Matching cached task results are redacted and recovery returns 410. It does not delete Profile, plans, copied snapshots or usage.

New practice records retain canonical topic references and catalog version. AI receives at most 24 relevant candidate resources, up to three practice activities and five validated resource IDs. Normal model settings and no automatic paid retry are retained. All browse/search/filter/sort/link operations are free of AI requests.

## Resource-card layout and free matching

The page uses one resource-card grid directly below its compact topic picker and filter toolbar. There is no separate skill browser, category accordion or selected-skill page section. Topic autocomplete reuses `/skills/topics` behind the toolbar. Matching saved practice appears after the grid when available; searchable practice history and career-support directories stay collapsed below it.

**Find skills for me · Free** refreshes at most ten deterministic suggestions. Confirmed Profile skills, Career Goals and the selected posting supply direct matches. Up to three one-hop related topics can follow direct matches, drawn only from explicit reviewed relationships. Catalog neighbors never imply a relationship. Suggestions explain their source and do not change filters until selected. No API key, provider request or usage event is needed. AI remains an explicit action for short practice ideas; at most 24 relevant resource candidates are sent.

Resource filters support repeated `fields`, `groups`, `providers`, `formats`, `accesses`, `levels`, `sources` and `topic_ids` query parameters. Values within a filter combine with OR; different filters combine with AND. The previous singular parameters and pipe-separated `topics` remain compatible. Responses add disjunctive `facets`, per-card `recommendation_reasons` and `display_title`; source titles, IDs and URLs are preserved. `job_id` scopes recommendations to an owned posting. `sort=recommended` (also legacy `relevance`), `title` and `provider` are deterministic. Recommended sorts direct selected-topic matches first, then personal source relevance and alphabetical ties. Without personal context the fallback is alphabetical.

Search covers titles, descriptions, providers, canonical topics and reviewed aliases. Selected filter values remain visible even when they produce zero results. Page changes show twelve cards; any topic/filter/search/sort change resets the page. Title and provider sorting apply across the single grid; related results carry a badge rather than changing the grid order.

## Desktop acceptance checks

1. Open Skills. Resource cards should immediately follow the compact controls. Confirm Browse skills, category accordions and Selected skill are absent.
2. Click **Find skills for me · Free** without an API key. Check suggestion reasons and that no topics are selected automatically or usage recorded.
3. Select Python and SQL, Codecademy and DataCamp, Course, and Freemium. Verify matches combine correctly. Search for a nonexistent phrase, check selections remain, then remove just the search chip.
4. Try Title A–Z, Provider A–Z, numbered pages and keyboard topic selection. Check Resource details for full metadata and the original source title.
5. Follow a saved milestone's learning link, reload and return. Verify the exact originating plan version and progress survive.
6. Open Practice history; cancel a named deletion, then delete a disposable set. Profile, plans and recorded usage must remain unchanged. History stays below the learning resources and is collapsed initially.
7. Use **Plan these suggestions in Action Plans**. Verify an unsent draft opens with no provider request. Optional AI practice requests remain separate; failures retain all previous suggestions.

Automated checks use simulated AI and fictional desktop accounts. Installed localhost and mobile layouts are outside this delivery.
