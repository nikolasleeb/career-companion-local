# Profile import and headline preferences

Upload / import holds resume uploads and LinkedIn profile PDFs. Parsing is local and makes no model, LinkedIn API or URL-fetch requests. English exported PDFs are supported conservatively; ambiguous passages and scanned documents need review or corrected source text. Existing uploads remain available.

Upload completion means ready to review, not that Profile has changed. Exact duplicates are skipped; possible overlaps start unselected. Users may add a new entry or select an existing entry and explicitly approve each nonempty field update. Source hashes, account ownership and record timestamps are checked at commit. The approval transaction applies all selected changes or none. Import receipts preserve before/after field values and source references; saved resumes retain their existing snapshots.

The optional professional-headline checkbox controls new resume snapshots. AI resume generation writes posting-specific headlines supported by reviewed evidence within the existing request. Disabled headlines are omitted at generation and rendering boundaries. Historical resumes and legacy saved headline text are retained, but new source snapshots do not reuse a generic Profile headline.

Career Coach opens on its landing page. Chat deletion removes that account's conversation, plan versions, research/index passages and cached task response content. It preserves Profile, Career Goals, applications and usage records. Running or cancelling chats must finish stopping before deletion.
