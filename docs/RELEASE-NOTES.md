# Career Companion Local 1.0.10

This release packages the current Career Companion features for localhost. It starts with an empty workspace and contains no hosted accounts, uploaded documents, private chats, cached jobs, API keys, notification credentials or vault keys.

- Review resume and LinkedIn imports in the actual Profile tabs, with full editable forms, standardized personal names, explicit source choices, common degree options, typed years and reliable multiword majors and project links. Imported details remain proposals until approved.
- Add project ZIPs, files and public GitHub links together. Preview and select materials before analysis. PowerPoint, Word, PDF, Excel and common image formats are supported alongside code and notebooks. Local text/OCR preparation makes no AI request; selected originals needing file or visual review are included only when you choose Analyze. Visual findings are labeled for review and originals stay in private account backups. Existing size and analysis limits apply.
- Mark individual projects explicitly. Project observations describe materials without assuming authorship, personal contribution or proficiency. Reviewed application answers remain the source of personal evidence.
- Control maximum response tokens in Settings → AI setup, or keep automatic limits. Larger projects receive more response headroom and compact source excerpts. Failed or incomplete analyses preserve previous results and are never automatically retried.
- Work Styles autosaves and free estimates no longer flash the global processing banner. Real AI actions keep their progress and cancellation controls.
- Certificate uploads support local PDF/image extraction with reviewable field suggestions. Project processing and AI work show a persistent progress banner; oversized uploads are rejected before transfer.
- Career Explorer provides occupation research, saved careers and optional Profile-course context. Career Goals and Career Plans support editable, reviewed guidance and application discussions.
- Career Coach supports private saved conversations, sourced guidance and optional explicitly shared Work Styles summaries. Work Styles summaries can be generated, revised and edited with separate save and sharing controls.
- Interview Practice includes recorded answers and transcription, with account-owned AI usage. Usage charts show costs and tokens across continuous time periods.
- Job Search adds broader employer/industry coverage and reliable listing windows. Settings provides API onboarding, selective cleanup, archive/delete review and explicit saved-key testing.
- Browser extension packages are version 1.0.4. Safari downloads remain source packages, not signed Safari installations.

AI remains optional and uses the account's own key. Uploading project materials alone never starts OpenAI analysis. Private AWS links remain references; export the files you want to analyze. No uploaded project code is executed. Non-PDF legacy Office file inputs provide text; export to PDF when visual charts are needed.

Before updating, finish active work and back up both Docker volumes. Verify the downloaded image archive against SHA256SUMS and follow LOCALHOST-QUICKSTART.md. The release workflow publishes only after both x64 and ARM64 images pass backend tests and clean-image smoke checks. Existing installations are never updated automatically.

Previous release: [1.0.8](https://github.com/nikolasleeb/career-companion-local/releases/tag/v1.0.8).
