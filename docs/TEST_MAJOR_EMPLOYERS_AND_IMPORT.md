# Test major-employer coverage and combined Profile import

Use fictional documents and a disposable account for import tests. Deployment does not import any documents, change Profile or run paid AI requests.

## Employer sectors and roles

1. Open **Settings → Job Search → Employer sources**. The section is **Employer business sectors**, with **Technology companies** and **All employer sectors**. Sectors select companies; your chosen roles select the work inside them.
2. For IT, software, data or cloud jobs across industries, select All employer sectors and choose the desired roles in Job Search. Selecting healthcare or finance restricts the company feeds, not your profession. Existing choices are kept.
3. Open Choose individual employers. Search AWS; Amazon / AWS should appear once. Search Capital One, Apple and Intuit. They are automated sources. Microsoft and the other official-site-only employers appear separately with links, without a searchable-employer checkbox or inflated counts.
4. Check the employer rows at desktop width and a narrow mobile width. Names and metadata should not overlap. Filtering the list must not clear selected employers.
5. Job Search source controls include **Major employer careers sources**. They use free public data. Old selections that enabled all three public ATS sources gain this source; an explicit new decision to disable it remains disabled. Custom employer selections still control which employers are checked.
6. Run a free manual search. Amazon/AWS and Apple use bounded official search results. Capital One and Intuit use permitted sitemaps and structured job details, never restricted search pages. Coverage is explicitly incomplete; source gaps do not mean no openings. Review full postings, especially Apple summaries, before tailoring.
7. Daily checks, For You and Ask AI inherit the same source and sector choices. For You and Ask AI can incur AI charges only when deliberately started. Automated verification used mocked AI providers.

## Review a resume and LinkedIn PDF together

1. Open **Profile → Upload / import**, including on a new account with no education yet. Choose a resume (PDF/DOCX/TXT), a LinkedIn PDF, or both. Selecting files does not upload or change Profile until Prepare review.
2. You may instead choose previously uploaded documents in the corresponding dropdowns. Choose at most one resume and one LinkedIn PDF. No re-upload is needed.
3. Click Prepare review. Each file has its own status. Profile remains unchanged. Clean new information starts checked; saved duplicates are skipped and uncertain extraction remains unchecked.
4. Review the single set of proposals grouped by Profile section. Exact duplicates appear once, labeled with both filenames. Similar records that differ require confirming they describe the same record; choose Keep these as separate records when they do not.
5. Resolve conflicting fields by choosing a source, editing the value or omitting an optional field. No source wins automatically. For list edits, use Edit details and choose the reviewed edited value.
6. Select only information you want to import. For an existing record, select the target and individually approve fields to update. Blank values cannot erase saved information.
7. Confirm the review and Import selected changes. Check the saved records and their original uploads. Repeated submission of the same approval must not create duplicates. Existing saved resume versions remain unchanged.
8. Correct text under View or correct source text. Reparse one document; this rebuilds proposals with fresh defaults, clears conflict choices and resets final confirmation. Review them again before saving.
9. Test Cancel/Close review: no Profile change. If one upload fails, the successful upload stays available; retry the failed file or choose Review available document. Each file retains the existing 10 MB/30-page limits.
10. If Profile or source text changes in another browser during review, an affected approval must be rejected and require a fresh review. Deleted or foreign-account sources cannot be imported.

For the detailed selection, normalization and discrepancy checks, see [Test the polished Profile import](TEST_PROFILE_IMPORT_POLISH.md).

## Verification and recovery

Both editions are built and tested with fictional accounts. Hosted deployment is preceded by protected database, uploads, configuration, vault-key and rollback-image backups. Installed localhost is left unchanged. Audited source and these instructions are pushed to GitHub without a release or tag. Backups exclude pending combined-review drafts; saved source files, imported records and import receipts remain compatible with account export/import.
