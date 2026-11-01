# Posting and Profile comparison

Application preparation has five navigation steps: **Posting → Comparison → Resume → Letter → Finish**. Existing Posting, Resume, Letter and Finish links retain their meaning; Comparison uses `#/resume?job=…&stage=comparison` with the same account-owned application identity.

Selecting a posting document starts no AI request. The existing upload confirmation reads the document and persists its extracted posting. On success, the application selects that posting and opens Comparison without an additional save step. Original text, extracted sections and posting edits remain under Posting. Manual entry and edits use **Continue to Comparison** to validate and save; this does not run comparison.

**Compare profile to job** explicitly starts the comparison using the current AI mode. Its stage, elapsed time, cancellation and status recovery appear beside the action. AI processing can take several minutes. A successful result remains on Comparison until **Continue to Resume** is chosen. Returning to results, history or another navigation step does not dispatch another comparison. Resume uploads and local builds remain available through Resume.

Comparison uses existing confirmed Profile and reviewed Supporting Details contracts. Individual skills retain their skill context, class details retain their class and status, and projects retain their ownership and attribution. Draft details and private eligibility information cannot become professional evidence. This workflow does not change qualification scoring or weaken evidence validation.

Task-start and individual task-status HTTP requests have a 30-second transport deadline. This does not limit server-side AI execution or posting uploads. A disconnected request retains its task identity/request token and offers **Check comparison status**. Reconnection reads the same task or reuses the original start token; it does not silently repeat provider work. Cancellation or failure retains older successful comparisons and requires an explicit retry. A saved result displays immediately, independently of a subsequent workspace refresh.

Preparation listings reopen Comparison for saved postings without resume work, saved comparisons, and active or failed comparison tasks. Existing resume work and selected document versions retain their established destinations. No database migration rewrites historical documents.
