# Project analysis progress

Use a disposable account with a mocked provider for automated checks. Do not start paid requests solely to verify layout.

1. Save a fictional project, open its Project materials dialog and choose enough files to make the dialog scroll. Scroll down to Analyze.
2. Click Analyze once. During file preparation, the top bar should remain visible while scrolling and say **Preparing selected project files** and **No OpenAI request in this stage**. This stage downloads and reads selected materials.
3. Once the server accepts analysis, the same global bar should show the confirmed task, then **Waiting for AI response** with total and stage elapsed times. Stop remains available when the server allows cancellation.
4. Close the dialog while analysis runs. The bar must remain on the main page. Reopen materials: the bar should move into the dialog and remain visible near the bottom. Opening, closing or polling must not start another analysis.
5. Verify the bar also stays visible in another long dialog and on a narrow mobile screen. Controls must remain accessible without horizontal scrolling.
6. Completion removes the running bar. A lost connection shows the existing recovery controls; Check saved status only reads status and never resends the paid request.

Both editions use the same progress behavior. Deployments and verification do not import Profile changes or make paid AI requests.
