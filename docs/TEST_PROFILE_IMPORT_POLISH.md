# Test the polished Profile import

Use a disposable account and fictional documents first. Preparing a review, cancelling it and closing it must leave Profile unchanged. No AI or LinkedIn API is used.

## Quick check

1. Open **Profile → Upload / import**. Select a resume and LinkedIn PDF, or choose documents already uploaded. Click **Prepare review**.
2. Clean new information should start checked. Saved exact duplicates should say **Already saved** and be skipped. Uncertain extraction should remain unchecked.
3. In **Personal Details**, found email addresses appear directly in **Choose Email**. Choose one, use **Enter another email**, or choose **Don’t import this field**. There should be no duplicate blank email input.
4. The same US number written as `202-555-0147`, `2025550147` or `+1 (202) 555-0147` should become `(202) 555-0147` without a conflict. Extensions remain distinct. International numbers retain explicit country codes.
5. A LinkedIn URL wrapped after a hyphen should be repaired when its continuation is clear or its PDF hyperlink supplies the full destination. A genuinely incomplete or different link must not be guessed.
6. Real disagreements should be highlighted with **Needs your choice**. This includes disagreement with information already saved in Profile. Choose a found value, enter your own, keep the saved value or uncheck the field/proposal.
7. **Next issue** should focus and scroll to the next selected item needing a decision. Section **Select all** and **Clear** should update selection counts. Unchecking an issue lets other resolved information proceed.
8. For a possible match with a saved record, choose whether to add a separate record, update a saved record or keep the saved information. Updating still requires selecting individual fields; empty imported fields cannot erase saved information.
9. Check the final accuracy confirmation, then click **Import selected changes**. Only selected and resolved information should be saved. Original uploads and existing saved resumes must remain.

## LinkedIn extraction checks

- Main profile text and the left sidebar should stay separate. Your name, headline and location should not appear as certifications.
- Grouped employment should keep the employer for each role. Durations and locations should not become employers, and promotions should stay separate roles.
- Education should retain the school, qualification and supplied dates. Different graduation dates must still require review; the parser must not fill in missing dates.
- Wrapped credential names should stay together. Sidebar skills should appear as individual skills rather than empty groups. Unknown passages remain under **Needs review · unassigned text**.
- Matching credentials from both documents should retain both sources. Similar wording is not proof that two different credentials are the same.

## Existing information and recovery

1. Save one fictional email in Profile, then prepare documents containing a different one. The difference must require a choice; simply preparing the review must not replace it.
2. Import selected information, then prepare the same documents again. Exact saved records should be skipped.
3. Use **View or correct source text** and reparse a document. A fresh review should appear with fresh defaults, cleared conflict choices and an unchecked final accuracy confirmation. User-corrected text must take precedence over automatic PDF extraction.
4. Cancel or close a review, including after edits. Profile must stay unchanged.
5. If one upload fails, keep the successful document and explicitly retry or review that document alone.
6. On a narrow screen, controls should stack without horizontal scrolling. Contact cards should use their own height instead of stretching to match a neighboring conflict card. Use Tab and keyboard controls to select values and reach highlighted issues.

## Rollout and rollback

Both editions are built and tested before rollout. Hosted data, uploads, configuration, vault key and the previous image are backed up before deployment. The installed localhost service is not changed. Audited localhost source and these instructions are pushed to GitHub without a release or tag. Deployment does not import Profile information or make paid AI requests.

For past education dates, GPA alignment and the exclusive same/separate choices, see [Education and import choices](TEST_EDUCATION_AND_IMPORT_CHOICES.md).

## Imported name capitalization

Try an all-caps or lowercase full name, including a hyphenated surname, apostrophe, accented letter, initials or suffix. The proposed name should use normal capitalization. If the other document provides the same spelling with existing mixed capitalization (for example Alex de la Cruz), that spelling takes precedence. Original source text stays available. Different names still need a choice. You can edit the proposal; preparing a review does not recase existing saved Profile information.

## Full forms in import review

- Prepare a resume, LinkedIn PDF or combined review with a fictional account. Prepared imports open Personal details and Resume content as unsaved drafts. Each selected record shows its full edit fields in the appropriate tab, without an Edit details dialog.
- In education, choose a common degree/qualification or Other / type my own. An imported custom qualification must remain unchanged until you choose or edit it. Check majors/minors, attendance dates, GPA, scale, classes and notes.
- Source alternatives sit beside the affected fields. Choosing a source or typing directly resolves that field; equivalent compatibility fields and generated education titles stay aligned. Confirm possible source matches explicitly. Unresolved selected conflicts still block approval.
- Clear a required field or leave a date partly entered: importing must focus the invalid control without saving. An unchecked proposal must not block other selected information or be imported.
- Edit fields, collapse source details, navigate internally or separate an unrelated match: existing draft recovery rules apply. Preparing, editing and closing review leave Profile unchanged. Only final accuracy confirmation plus Import selected changes saves information.
- Check wide and narrow screens, keyboard controls and labels for multiple education/date/course fields. Test the same qualification choices in the ordinary Profile education editor and preserve custom values when editing existing records.

## Multiple project links

In Resume content’s imported drafts, add a second project link and type it character by character. New empty rows and partial URL text must remain visible; editing or removing one link must preserve the others. Check the five-row limit, duplicates/empty rows at save, invalid URL blocking, desktop/mobile layout, and saving/reopening multiple links. Repeat in the ordinary Profile project editor. Cancelling a review or editor must leave saved links unchanged. Adding a link never fetches its contents or starts AI analysis.

## Certificate form filling

Upload a fictional text PDF, scanned PDF, PNG and JPEG certificate in import review and in the ordinary credential editor. Local extraction should fill empty fields while preserving the selected attachment and existing values. Existing disagreements need explicit Use extracted choices. Check issuer, dates, credential ID/link, source excerpts and OCR warnings. OCR runs locally in English, with bounded concurrency, time, image dimensions and extracted text; incomplete processing stays visible and can be retried. Do not infer credential validity. Preparing, uploading and extracting do not save Profile or call AI. Confirm stale attachment results cannot fill a replacement certificate.

Local source installs need Tesseract with English language data and Poppler for image/scanned-PDF extraction. Both Docker editions include these tools. Missing OCR tools produce a recoverable message; native PDF text extraction and manual entry remain available.

## Imported drafts in Profile tabs

Prepare a document in Upload / import. It should take you to Personal details when contact information exists, otherwise Resume content. Review and correct drafts in those actual tabs; Upload / import only retains document controls and links back to the drafts. Internal tab changes and browser Back/Forward retain entered fields, selections and blank link/subject rows. Next issue can move between the two tabs. Final import approval is in Resume content and checks selected fields in both tabs, taking you to a hidden invalid field if needed. No data reaches saved Profile, onboarding or evidence before approval. Discarding drafts leaves Profile unchanged. Saving imports returns the usual saved Profile workflow.
