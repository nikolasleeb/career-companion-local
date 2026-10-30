# Skills catalog and practice history

Skills provides deterministic resource browsing and short practice ideas. Action Plans owns saved timelines, milestones and progress; the handoff opens a draft and never submits an AI request.

The reviewed catalog is `backend/app/skills_catalog.json`, version `2026-10-30.1`. It contains 516 concrete skills and 512 distinct learning destinations, counted once by primary field:

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

## Desktop acceptance checks

1. Open Skills and search **Spark** in Browse skills. Select it; verify the Quick Start and labelled related resources. Try PySpark, Spark SQL and Structured Streaming.
2. Try field/subcategory/source filters, A–Z/resource-count sorting and the page selector. Filter resources by provider, type, access and difficulty; confirm counts and direct/related headings update.
3. Open a milestone learning link, reload, then use **Back to this milestone**. Check the same plan version and progress return.
4. With saved Git/Python suggestions, select Spark. A Spark-specific empty state should appear unless matching Spark suggestions exist; the older set remains in collapsed **Practice history**.
5. Search/open a historical set. Cancel its named deletion confirmation, then test deletion with a disposable set. Profile, saved plans and daily usage must remain unchanged.
6. Click **Plan these suggestions in Action Plans** beneath a saved set. Verify the composer contains the topics, activities and resources, with no request started. Generating a plan is a separate AI action.
7. Optional paid test with your own key: request new suggestions, then change topics/target to verify matching and history. A failed request must keep previous sets.

Automated checks use simulated AI and fictional accounts. Installed localhost and mobile layouts are outside this delivery.
