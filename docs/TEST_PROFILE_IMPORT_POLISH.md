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
