# First sign-in, API connections and navigation: user test guide

Use a fictional test account for experiments. No API key or paid request is needed for steps 1–7.

1. Sign into an account without reviewed education at the site root. It should open **Profile → Upload / import**, even if that account previously visited another page.
2. The welcome guide should appear once. Choose **Set up API connections**. In Settings, check the OpenAI and optional Adzuna controls, plus the server-managed O*NET and USAJOBS statuses. A fixed mask indicates a configured server credential; it does not reveal any portion of the actual key. Opening this page does not test providers.
3. Reload. The welcome should remain dismissed. Use **Reopen welcome guide** to show it again, then dismiss it with Escape or its buttons. Dismissal is saved to your account and also applies in another browser.
4. With no education or AI key, open each Resource. Career Explorer, assessment scoring, written guides, saved results and manual interview questions remain available. AI actions explain that your account needs a saved key. Applications and Job Search still explain that reviewed education is required.
5. In Profile → Career Goals, type a draft without saving. Visit Skills, then use browser Back. The draft should still be there. It should not appear anywhere in the URL.
6. In Career Explorer, open an occupation, close it, then use Back and Forward. The occupation details should return and close. Repeat with Settings tabs, Career Plans chats and plans, interview sessions/questions, applications and application tabs, and the floating Career Coach panel. History navigation must not send a new AI request.
7. With a completed fictional account, edit an application note and use Back. Cancelling the discard prompt should retain your note; accepting should leave the record. Refresh a saved record URL to check direct linking. A deleted or unavailable record should show an error and a way to choose another record.
8. Optional: add your own provider credentials in **Settings → API connections**. Saving/replacing/removing credentials does not test them. Adzuna's explicit test consumes one provider request. Model, reasoning and speed choices remain in **AI setup**. Employer sources remain in **Job Search**.
9. Optional paid check: with an empty Profile and a saved OpenAI key, request general career guidance, a skills plan or an interview question. It should give general guidance without inventing your experience. Review the cost history afterward. Voice actions still require the relevant question, microphone permission and explicit paid actions.
10. Sign out and use a different account. Previous account drafts, records and welcome state should not carry over. Check the connections page and navigation at a narrow mobile width as well.

## Operational boundary

Hosted rollout preserves the existing pilot access policy, account data, credentials, uploads and vault key. The previous hosted image and consistent data backup are retained privately before deployment. Sanitized localhost source is committed to GitHub; the installed localhost service is not updated. No release or Git tag is created.

The baseline public-source commit before this change is `8b004f13adc8a2a7f9be3f82d8aed110c35ed92b`. Use repository history to compare or revert source. Restoring a hosted data backup can overwrite later user activity and requires a deliberate operator decision.
