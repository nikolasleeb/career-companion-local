# Profile, AI and application data use

This table describes version 1.0.12. “Eligible” means the feature may select relevant context, not that all saved data enters every request. AI requests require a user action and the account’s own provider key. Saving manual information and routine application autofill do not call AI.

| Saved information | Local Profile / documents | AI use and conditions | Application autofill |
| --- | --- | --- | --- |
| Confirmed jobs, education, classes, projects, volunteering, skills and certifications | Professional content and master resume; tailored documents use selected evidence | Relevant confirmed sources, subject to personalization and feature selection; preserve ownership, dates and academic context | Recognized professional fields from saved records |
| Confirmed Supporting Details | Shared linked record displayed with its related entries | Approved professional evidence only; shared links do not create additional accomplishments | Only supported mappings; not arbitrary insertion into every field |
| Pending, unconfirmed or archived Supporting Details | Review/history only | Excluded from professional qualification evidence; explicit review actions can inspect proposals | Not treated as confirmed experience |
| Project links, selected project materials and syllabi | Private source attachments and review workspace | Explicit analysis can send selected excerpts; a saved URL alone is not an analyzed source. A syllabus alone cannot establish personal experience | Not pasted into unrelated employer fields |
| Career Goals | Aspirations kept separate from professional qualifications | Shared goals can personalize guidance; explicitly chosen goals can assist open-ended application answers. They do not establish skills or accomplishments | No automatic goal-to-field insertion |
| Reviewed Work Styles summary | Separate self-description; excluded from master resume export | Shared summary can guide wording and advice. It is not qualification evidence | No automatic personality claims |
| Raw Work Styles answers, detailed scores and assessment report | Local assessment and results | Excluded from ordinary guidance, Career Coach retrieval and resume generation. Explicit summary drafting can use up to five broad domain averages and interpretations, work-comparison choices, notes and the saved summary, plus confirmed work examples when explicitly selected; it excludes raw ratings and sensitive facets | Not autofilled |
| Resume name, email, phone and city/state/country | Allowed contact header; existing resume location formatting is retained | Professional-context projection uses allowlisted evidence rather than the full Personal Details record; explicitly uploaded documents may contain contact text | Saved contact values for recognized controls |
| Legal/middle/family/preferred application names, street lines and postal code | Encrypted private storage; excluded from optimizer resume headers and ordinary account exports | Excluded from general AI context and professional-evidence retrieval | Explicitly saved values; preferred name can follow legal first name |
| Citizenship, authorization, sponsorship and other private disclosures | Encrypted, separate from professional Profile and ordinary exports | Excluded from AI prompts, resumes and cover letters; no inference from residence or citizenship | Saved Yes/No authorization and sponsorship can fill matching unqualified questions. Other/ambiguous disclosures require review |
| Applications, finalized resumes/letters and saved guidance | Account-owned history | Career Coach can retrieve eligible allowlisted saved records when personalization permits; generated guidance remains guidance, not new evidence. Unfinished drafts and unknown record types are excluded from automatic retrieval | Exact approved document versions only; uploads remain a user handoff |
| API keys, passwords and verification codes | Credentials are separate; employer passwords/codes are not collected by the extension | Provider keys authenticate requests but are not prompt context; employer passwords/codes never enter AI | Passwords/codes are never read, stored or filled |

## Permission and review rules

- AI personalization controls automatic professional-context use. Legacy sharing choices remain effective until explicitly saved under the current control; enabling personalization does not approve unreviewed facts.
- Work Styles must have a reviewed safe summary. Ordinary guidance currently receives the summary, not the full assessment report, even if an older stored report-sharing flag exists.
- Source relationships provide context and attribution. They cannot turn one project into several accomplishments or credit a teammate’s work to the applicant.
- Imports and source analysis do not silently confirm experience. Review suggested facts before employer-document use.
- Existing employer-form values are preserved. Country/state choices must match actual available options; unresolved values and failed readback stay visible for review.
- Saved authorization is distinct from citizenship and residence. Combined now-or-future sponsorship requires both saved timeframes; missing, Unsure, qualified or ambiguous questions stay manual.
- Protected recovery backups retain encrypted private data and require the matching vault key. Ordinary account exports exclude private-vault values.
- Turning off sharing affects new requests. Historical conversations and saved snapshots are not retroactively rewritten.

## Source checks

The table follows `backend/app/profile_context.py`, `profile_answers.py`, `personalization.py`, `work_preferences.py`, `work_style_summary.py`, `career_goals.py`, `coach_access.py`, `assistant_context.py`, `personal_details.py`, `application_values.py`, `application_agent.py` and the relevant feature-specific context builders. These are explicit projections, not permission to send complete database records to a provider.

The public localhost edition and separately operated hosted edition share these data-use boundaries. Public release artifacts contain no user accounts, private data or hosted credentials.
