> Employer counts and application cleanup controls were updated. Use [Test employers and cleanup](TEST_EMPLOYERS_AND_CLEANUP.md) for the current steps. The API-key and other regression checks below still apply.

# Test broader job sources and account controls

Use a disposable account for deletion tests. Deployment never runs account cleanup or a paid key test. Your installed localhost service is not updated by this rollout.

## Employer sources

1. Open **Settings → Job Search**. The catalog now has **298 distinct curated employers** across 299 supported feeds. Each employer retains its verification date and observed job count in the catalog; an empty feed is possible. Coverage depends on the supported public Greenhouse, Ashby and Lever feeds and is not a complete job-market index.
2. Under **Employer industries**, select **Science & research** and another industry. The selected employer count should change. Multiple tags do not duplicate an employer.
3. Expand **Choose individual employers**. Change one employer: the selection should say **Custom**. Choose **All employers** to restore the complete catalog.
4. Open Job Search → Search options and sources → Manage search sources and employers. It should show the same choices. Search a role such as research assistant using an appropriate location and career level. Industry chooses company feeds; role filters choose postings within those companies. An industry does not promise a specific number of matching jobs.
5. Daily checks and **For You** inherit the saved employer selection. USAJOBS and Adzuna remain separate source choices. Industry presets resolve against the catalog each time a search runs; later matching additions join automatically. Custom selections stay explicit.
6. To add an employer, expand **Add an employer careers page**, enter its name and supported careers-page URL. Manual platform identifiers remain under Advanced setup. Unsupported sites should give a useful error.

**Listing availability window — 30 days:** A listing expires from current results 30 days after its last source confirmation, or sooner if closed. A new confirmation extends that window. Applications and their documents stay saved.

**Reuse public feed results — 6 hours:** Searches and scheduled checks can reuse a downloaded public employer/community feed for six hours. Explicit Refresh can request an earlier update. This is separate from the Posting date filter, which still offers up to 90 days. Neither timer changed in this rollout.

## Backup controls

1. Open **Settings → Account & backups**. Download and Import should be matching buttons, side by side on desktop and stacked on mobile.
2. Download a backup before testing permanent deletion. Ordinary backups exclude API credentials and private-answer vault data.
3. Import a fictional backup. Its filename and 256 MB limit should appear below the button. Import adds records with new IDs and preserves existing records; it is not a replacement/reset operation.

## Applications by date range

1. Create a few fictional applications with different Date applied values. Add a document and, optionally, offer information.
2. In the separate **Manage applications** card, set both required From/Through dates. Date applied is used, otherwise Date added. Dates include both endpoints.
3. Click **Archive applications**. Review the preview, then confirm without entering a password. Statuses, dates, documents, offers and conversations should remain. Archived entries leave current lists and charts, while Career Coach can retrieve them as historical records.
4. Restore the archived record from the Applications page. Eligible restored entries return to current lists and charts.

## Selective permanent cleanup

1. Use a disposable account and save unfinished work first. Cleanup refreshes browser views and clears recovery drafts to keep removed data from returning. Initially every category should be unchecked. Open a collapsed group to select its categories. Applications have a separate date-range card.
2. Select one category and choose **Review selected deletion**. Review exact affected records, files, shared records kept, and historical-copy notices. Changing the selection closes the old preview. A preview expires after ten minutes; a changed account requires a fresh preview.
3. Cancel first and confirm nothing changed. Previewing never deletes information.
4. Preview again. Enter **DELETE** and the account password, then confirm. Wrong passwords fail without deleting anything. The operation can be checked again without applying deletion twice.
5. Login, API connections, model/source preferences, welcome dismissal and Usage & costs should remain. Clearing goals disables goal sharing; clearing Work Styles summary or assessments disables the corresponding sharing. Removing education re-enables the existing setup requirements for Job Search and Applications; Resources remain accessible.
6. Unselected uploads, resumes and conversations can still contain historical copies. They are separate cleanup choices. Retained references to removed sources become unavailable references; old approved proposals and recovered task results must not silently recreate Profile evidence.
7. Permanent application deletion also deletes its offer and exclusive uploaded attachments. Shared files and independently retained generated resume versions remain. The preview lists shared records kept.
8. File removal follows database removal. A pending status means the records are unavailable and the server is retrying disk removal. Return to this page to see the status. Do not assume a failed file operation is complete.
9. An affected active task, application-assistant run or daily check should block cleanup; it is not silently cancelled. Finish or stop it explicitly, then preview again.
10. If another browser had unsaved edits, stale writes must be rejected. Reload the account state. Cleared drafts and recovered results should not repopulate the deleted data.

Cleanup cannot erase backups already downloaded or held by the operator. Selected information is permanently removed from the live account after confirmation; keep a backup if you may want it later. Explicitly importing a backup may restore information with new IDs.

## Optional paid OpenAI key test

1. Open **Settings → API connections**. Opening Settings and saving a key make no provider request. Without a saved account key, the test is disabled.
2. Save your own key, then inspect the model and charge estimate beside **Test saved key · small AI request**. A ChatGPT subscription alone does not fund API usage.
3. Typing an unsaved replacement disables the test. Save the replacement or clear the input before testing.
4. Only if you want to incur the displayed small API charge, click Test. It sends one fixed sample prompt using the selected text model, its lowest supported reasoning, Standard speed, a 512-output-token cap and no Profile, tools or web search. It does not alter saved AI settings, automatically retry or switch models.
5. Success shows the tested model/time and updates the connection badge. It checks text generation, not voice or every AI feature. Usage history records **API connection test** separately.
6. Invalid credentials, denied model access, billing/quota, rate limits and temporary failures should have distinct messages without exposing provider response details. Use Stop while running. If connectivity is lost, use **Check saved test status · no new request** before starting another test.
7. Replacing/removing the key invalidates previous success. A result from an older in-flight key cannot mark its replacement as tested. No real key test is run as part of deployment verification; automated tests use fictional keys and a mocked provider.

## Visual and keyboard checks

Try desktop and a narrow mobile viewport. Backup buttons should match. Employer controls and cleanup previews should fit without horizontal overflow. Tab through controls, use Space to toggle checkboxes, and confirm password/typed-confirmation fields have labels. Navigation should continue to support browser Back/Forward.

If you use the browser application assistant, the included Chrome/Safari packages are version 1.0.5. Update the extension and reload the Career Companion tab so it can send the account data revision after cleanup.
