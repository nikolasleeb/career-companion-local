# Major-employer coverage — 2026-10-28

The catalog contains **302 distinct searchable employers across 303 feeds**, plus **16 official careers links outside automated coverage**. All previous feed identifiers remain. AWS is an alias/division of Amazon and is counted once with Amazon.

## New automated sources

| Employer | Method | Bound | Observed query count |
|---|---|---|---:|
| Amazon / AWS | amazon_public_search | Two pages per role within a 40-second source budget | 200 |
| Apple | apple_public_search | Two pages per role within a 40-second source budget | 40 |
| Capital One | official_sitemap_jobposting | Sitemap plus at most eight matching structured detail pages within 40 seconds | 8 |
| Intuit | official_sitemap_jobposting | Sitemap plus at most eight matching structured detail pages within 40 seconds | 8 |

Observed counts are bounded verification samples, not total openings. The six-hour cache, six concurrent source fetches and 180-second employer phase remain. Partial inventories never close missing jobs. Amazon and Apple expose published search data; Apple summaries do not establish full requirements. Capital One and Intuit restrict search-page crawling; only permitted sitemap and JobPosting detail URLs are used, with robots rules checked on each uncached scan.

## Official careers sites only

These employers have no verified automated adapter in this release. A website link does not imply their postings were fetched. A blocked automated identity probe is recorded, rather than reported as a successful feed check.

- [Microsoft](https://careers.microsoft.com/)
- [Google](https://www.google.com/about/careers/applications/)
- [Meta](https://www.metacareers.com/)
- [NVIDIA](https://www.nvidia.com/en-us/about-nvidia/careers/)
- [Adobe](https://careers.adobe.com/)
- [IBM](https://www.ibm.com/careers)
- [Boeing](https://jobs.boeing.com/)
- [Lockheed Martin](https://www.lockheedmartinjobs.com/)
- [Northrop Grumman](https://www.northropgrumman.com/careers/)
- [RTX](https://careers.rtx.com/)
- [Siemens](https://www.siemens.com/global/en/company/jobs.html)
- [JPMorgan Chase](https://careers.jpmorgan.com/)
- [Bank of America](https://careers.bankofamerica.com/)
- [Wells Fargo](https://www.wellsfargojobs.com/)
- [Citi](https://jobs.citi.com/)
- [Goldman Sachs](https://www.goldmansachs.com/careers/)

Verification URLs, dates, coverage classifications and observed query counts are retained in `backend/app/employer_catalog.json`. Existing ATS-directory CC BY 4.0 attribution remains.
