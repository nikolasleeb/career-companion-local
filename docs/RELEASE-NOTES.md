## Source update after 1.0.8 (no new release or tag)

Adds a global read-only Career Coach, Career Plans, reviewed Work Styles preferences, structured goals, five-job discovery, broader Skills, saved interview conversations and optional visual responses. Extension packages are 1.0.4. See [implementation notes](BROADER-CAREER-SUPPORT.md).

# Career Companion Local 1.0.8

This release brings the current Career Companion features to the localhost edition. It starts empty and includes no hosted accounts, documents, chats, cached jobs, API keys, notification credentials or private vault keys.

- Profile now has Upload / import, Personal details, Resume content, Career Goals and Private application answers tabs. Unsaved values survive tab switches.
- Import resumes and LinkedIn profile PDFs locally without an API key. Review exact duplicates, possible overlaps and field-by-field updates before committing. Originals, previous evidence and saved resumes remain available.
- Personal details has separate website, GitHub and LinkedIn fields. An optional headline checkbox enables posting-specific, evidence-supported headlines within existing AI resume generation.
- Career Coach opens on a landing page. Keep multiple private chats, research current questions when needed, save sourced roadmaps and delete chats deliberately. Career Goals remain separate from qualification evidence.
- Stop AI actions from one shared progress banner. Previous saved work and editable drafts are preserved; incurred or unknown provider usage remains recorded.
- Public employer feeds and community job listings support ordinary job search without API keys. Search result filtering, page sizes up to 100, optional AI matching and job examples are available.
- Public feeds can reuse validated source coverage across local accounts. Disposable jobs default to 30-day retention, with configurable localhost retention and reliable earlier closing dates; saved/application evidence is preserved.
- Settings groups AI setup, usage/costs, job sources, account/backups and App & storage. Update checks distinguish a published release from newer source code and never install or restart anything.
- The workspace connection badge checks the authenticated app session. A saved AI key is not a provider verification.

The localhost edition retains local-only access, local registration and account-owned AI keys. Its optional integrations require the installer's own settings. The hosted pilot's special Adzuna trial access, invitations, domain and delivery configuration are excluded. The extension remains 1.0.3; Safari downloads are source packages, not signed Safari installations.

Back up both Docker volumes, finish active work, verify the archive checksum and follow LOCALHOST-QUICKSTART.md before updating. Both x64 and ARM64 images and downloadable archives are tested by the release workflow before publication. Existing installations are never updated automatically.
