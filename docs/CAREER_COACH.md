# Career Coach

Career Coach is an account-owned resource for exploring goals and building a practical learning roadmap. It supports multiple saved chats, editable titles/goals, optional time and budget preferences, follow-up questions, roadmap versions and a separate progress checklist. Completed activities never become Profile evidence automatically.

The first screen and all history/progress controls make no AI calls. Plan generation and research refresh are explicit paid actions using the account's existing key and AI settings. A regular follow-up uses local retrieval and the chat's saved research, without another web-search request. Goal and chat changes are free. New research never changes earlier source snapshots or roadmap versions.

## What the RAG pipeline actually does

1. Read reviewed professional Profile passages and the chat's goal. Private disclosures, Work Styles responses, contact details and unreviewed records are excluded.
2. On a new plan or explicit refresh, derive public search topics from a curated role/skill vocabulary. Raw Profile text, employer names, contact details and the user's raw goal are not sent to web search.
3. Make at most one Responses API research request, with up to four built-in search-tool calls. Fetch at most six cited official public pages with the existing DNS-pinning, redirect, size and private-network protections. Unreadable pages do not establish facts.
4. Index public editorial guidance and account/chat-owned research passages in SQLite FTS5. Use role aliases, BM25 ranking and a bounded mix of fetched and original guidance passages to select at most twelve chunks before generation. No vector service or embeddings are required for this first version.
5. Generate a structured response using those chunks, reviewed evidence and bounded relevant conversation context. Validate exact Profile quotes and source passages, attach server-owned source metadata and save the frozen response. Unsupported prices are left unverified. Research older than thirty days is flagged for refresh.
6. A new-plan action saves a roadmap; follow-up chat can propose revisions, which require the separate **Update roadmap** action. An unchanged action retains its checklist identity and progress across versions.

The bundled library contains original, source-linked editorial guidance across technology, business, engineering, health, education, arts and science. These summaries are labeled original app guidance; they are not quotations from provider pages and do not establish current prices, eligibility or labor statistics. Fetched sources show their check date and publication date when supplied. Source passages and Profile evidence can be inspected in the conversation and recommendation drawers.

The application follows a fixed pipeline. It does not run an autonomous tool-selection loop, enroll in courses, buy certifications, change Profile facts, submit applications or run scheduled AI coaching.

## Persistence and operations

`/api/career-coach` provides account-scoped chat/history, goal editing, explicit paid actions, read-only action recovery, roadmap acceptance and progress endpoints. Existing task APIs report stages and outcomes. Usage is recorded under **Career Coach** in Settings → Usage & costs.

Paid request tokens are scoped to the account and chat and deduplicate repeated starts. Unknown network outcomes are not automatically dispatched again; recovery is read-only. The browser stores action references without the prompt and keeps typed message drafts in account/chat-scoped session storage. Chats retain their complete history while the model sees only bounded relevant context.

Chat, message, plan and research entity records participate in account backup/import/deletion. Imported source material is never added to the shared public index. Original message dates and source/Profile snapshots survive restore; account IDs and record references are remapped. Profile changes flag earlier roadmaps without rewriting them. The hosted education gate, storage quota and existing access controls remain in force.
