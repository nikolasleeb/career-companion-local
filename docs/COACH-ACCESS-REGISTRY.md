# Read-only Career Coach access

`backend/app/coach_access.py` is the account-content registry. New features must supply an explicit eligibility rule and readable projection here; arbitrary entity dumps, SQL, URLs and write tools are not model capabilities. Each projection has an account-owned record ID, revision, status and category. `assistant_context.py` builds an ephemeral account-scoped index and retrieves relevant excerpts (18 chunks / 26,000 characters), honoring conversation pin/exclude controls. Public catalog sources can also be excluded.

| Source | Eligibility and projection |
| --- | --- |
| Profile | Confirmed education, coursework, employment, projects, volunteering, skills and certification names/issuers/dates. Coursework remains learning context. No credential identifiers or personal contact/settings dump. |
| Supporting Details | Confirmed professional experience only; no eligibility/private answers or pending proposals. |
| Documents and project sources | Already prepared text attached to confirmed professional records. Project sources also require completed saved analysis. No automatic upload reading/OCR/analysis. |
| Project analysis / Explorer review | Completed saved findings, source passages, limitations and outdated status. Generated interpretation remains separate from applicant evidence. |
| Resumes / letters | Final saved documents, not draft workspaces, unfinalized revisions or pending proposals. |
| Applications / postings | Professional posting and tracking fields only. No private answers, offers, sensitive disclosures or workflow drafts. |
| Careers / searches / plans | Saved career interests, applied search criteria, saved skills plans and explicitly saved reviewed Career Plans. |
| Interview feedback | Completed saved coaching output, excluding raw answers and proposed useful-details records. Not confirmed applicant experience. |
| Career Goals | Existing automatic-guidance consent remains required. |
| Work Styles | Reviewed summary requires existing guidance consent. Report/scores additionally require existing explicit Coach report permission. Raw questionnaire answers never enter retrieval. |

Generated records retain provenance checks. Nested source snapshots referencing private material, conversation-only offers, deleted/foreign/unconfirmed sources or revoked sharing are ineligible; excluding an upstream source also excludes dependent generated records with that provenance. Sensitive-line filtering remains an additional defense for prepared text. Sources and revisions are checked again after the provider returns. A changed permission/source fails the new response while preserving previous saved messages. Already saved conversations remain account-private historical records; unavailable gated source snapshots are excluded from subsequent model history.

Offers may be explicitly selected for the current Coach conversation, never retrieved automatically or carried through other saved outputs. Text inside a source cannot grant permissions. Adding a source adapter grants no writing capability.

# Published BLS and occupation reads

`coach_bls.py` exposes four validated internal operations: `find_occupations`, `find_salary_areas`, `wages`, and `compare_metros`. They call shared bundled catalog/wage helpers; no external request or AI occurs during the read. The explicit Send · AI request may propose one round of at most six reads, followed by a cited answer. Further lookup rounds fail without automatic paid retries. Existing task cancellation, token settings, deduplication and rollback apply. Results and source metadata are stored with the answer and survive account backup/restore.

Occupation resolution uses official titles and established alternate titles. Unresolved abbreviations such as DE require clarification. Specialty wages disclose the broader SOC occupation. Metro comparison defaults to ten results by median annual wages, caps at twenty and supports state/area restrictions and alternate percentiles. Cross-state metros belong to every listed state. Hourly rankings are separate. Missing/suppressed observations never receive national values for ranking. Published bounds retain their marker and floor; identical floors do not establish distinct ranks. Geography, reference year, units, percentiles and official source URLs accompany results. Dollar amounts and exact source quotes are validated before saving.

The bundled OEWS distributions describe published pay across workers, not starting salary, experience-based pay or cost-of-living-adjusted purchasing power. Local tables do not force web research; questions requiring facts beyond the dataset can still request research. Selected Explorer salary area is part of explicit occupation context; legacy links default to United States.

# Desktop interface

The salary-area combobox filters state names/abbreviations and official area names, including all participating states. DMV, NoVA, Northern Virginia and Washington DC variants identify the broader Washington–Arlington–Alexandria, DC–VA–MD–WV metro. Typing does not change the committed selection; selection/Enter commits, Escape/blur restores. Saved searches preserve official IDs.

Compare actions use standard secondary buttons, with 32 pixels before the comparison section. The optional contextual AI review is initially collapsed immediately above skills, keeping status, cost, summary consent and saved findings together. Work Styles management remains only in Profile; external management shortcuts and its Find roles & careers block are removed. Assessment/report data, resumable drafts, autosave, sharing and legacy routes are unchanged. Job Search → For You retains discovery.
