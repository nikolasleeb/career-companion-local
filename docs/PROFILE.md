# Resume content and full master resume

Profile keeps concise overview bullets on each entry. **Supporting Details** holds deeper examples of personal actions, methods, context, and supported outcomes. Open an entry's Supporting Details to add, edit, remove, or restore a supporting detail. There are no ordering arrows; saved order is retained and new details append. Removing a detail archives its record and source history. Manual editing and exporting make no AI requests.

## Classes and projects

Class management lives on the main education card, alongside Projects. **Add class** offers manual names or **Upload transcript**, which opens the picker directly. PDF, DOCX and TXT transcripts retain the existing 10 MB / 30-page limits. Review and select locally extracted class names before adding them; names append, duplicates are skipped, and existing class IDs, statuses, syllabus records, details and project connections stay intact. Cancelling the picker or a failed save preserves the draft and selections. The transcript itself is not saved.

Each class opens its existing editor, syllabus controls, and individual Supporting Details. A successful save immediately updates the editor and class card from the server response; older list responses are ignored. Only unsaved edits are cached. Conflicts retain those edits and offer **Refresh saved version** before retrying.

Unspecified classes default to Completed after the education attendance end date, or expected graduation when no attendance end exists. The boundary uses the account’s configured day-boundary timezone (`usage_timezone`), falling back to UTC when unset. A month/year takes effect after that month ends; a year-only date takes effect after that year ends. This applies to existing classes and later transcript/manual additions. Manual Completed, In progress, Planned, and explicit Unspecified choices take priority. The additive `course_items[].status_override` flag preserves that choice through old clients and backup/import; backups retain raw stored status rather than freezing a date-derived default. The class-list response supplies effective `status` and `status_source`. Completion status is administrative context, never evidence of proficiency or personal accomplishment. Status and syllabus coverage stay in the app; the full master export includes class names and reviewed personal details only. The education editor has no duplicate class list or transcript controls.

Jobs and education entries offer **Add project**. Create a project there or attach an existing one. A project is saved once; editing a shared project anywhere updates the same record. The separate Projects section counts and shows standalone projects; attached projects are counted separately. All project materials and links are preserved.

The employment editor no longer offers education/course links. Previously stored academic relationships remain intact in ordinary saves and backups.

## Shared project timelines

Only projects connected to **two or more distinct education/job entries** have timeline controls. Several courses under one education entry count as one parent. Standalone and single-parent projects show one project date pair, with no timeline assignment button, stage dates, stage preview, or Applies to controls on details. Splitting an overview into several bullets does not require timeline assignment for these projects.

Project date controls show optional month and year, including year-only values. Untouched stored days remain intact; editing a date replaces it at month/year precision. Cards and master exports display project dates without days. Shared projects keep overall project dates and optional stage dates, including an **In progress** end-date option. The current parent's stage appears first. Each overview bullet and Supporting Detail can apply to the whole project, selected stages, or remain awaiting assignment. New content added through a parent uses that parent context.

Adding a second connection freezes existing single-parent applicability to the original parent, including legacy Whole project statements. Deliberately reviewed overview assignments can expand applicability in that same save using the additive `reviewed_project_scope_ids` structure-save field. Detaching a stage requires resolving affected overview/detail assignments atomically. Stable IDs, dates, scopes, review status and provenance survive relationship changes and backup remapping.

Previously saved single-parent stage dates remain visible for reference in **Manage connections**; they do not override project dates in the master export. Existing explicit project-only restrictions remain restrictions until edited or deliberately resolved, even when timeline controls are hidden. Unchanged content is never silently promoted into a job claim.

## Evidence ownership

Project Supporting Details belong to the project, with no automatic copy into a job's own details. Resume, cover-letter, comparison and coaching consumers may use that evidence through its applicable project connection or assigned stage. Unassigned shared-project content cannot substantiate a particular job or education stage. Historical saved documents remain unchanged.

Within each job/education subtree, the master export displays a legacy detail linked to both parent and project once, under its project. Deduplication uses saved record identity, not matching wording. Separately saved job details remain separate; repetition under different applicable jobs is preserved.

Individual skills have their own Supporting Details. Skill-group legacy details stay awaiting skill assignment until explicitly assigned or archived. **Skills** and **Certifications** appear as separate groups, with Certifications immediately after Skills in Profile and both master exports. Add/upload controls for credentials live in Certifications. Storage remains `category: skills`; certification records, entry-level details, attachments, credential links and dates retain their behavior. This presentation split does not change global onboarding counts or readiness.

## Full master resume

Choose **Export full master resume** in Resume content for PDF or Word. Both use one versioned snapshot; a changed Profile requires refreshing the summary. Exports include complete confirmed professional content without AI rewriting or one-page fitting. Private application answers, Work Styles, AI personalization, syllabi, and source history are excluded.

The document hierarchy uses 16 pt main sections, 14 pt degree/job headings, 12.5 pt Coursework/Projects subsections, 11.5 pt nested project titles, 11 pt regular body/course/skill/detail text, and 10 pt metadata. Indentation and hanging bullets show nesting; headings stay with first content, while long details may continue across pages. Course names appear once, with personal details one level deeper. Links and page numbers remain visible.

Single-parent projects export their own dates only. Shared projects prefer explicit stage dates, otherwise labeled whole-project dates. Attendance and graduation dates never become project dates. Pending timeline content appears once at project level only for shared projects; legacy project-only content on simple projects remains visible once beneath its project without inventing job-level applicability.

Entry and detail-list saves check the expected version. Conflicts or failures preserve editor content. Supporting Detail and class drafts are account/entry scoped in browser storage. Optional `timeline_enabled` response metadata is additive; old clients can keep saving without it. Omitted detail scopes preserve existing assignments rather than resetting them.

## Locating pending project assignments

The Profile review queue and export dialog list each confirmed shared project with unassigned overview bullets or confirmed, active personal details. Each list gives separate overview/detail counts and direct buttons to open the appropriate assignment editor. This is attribution work, distinct from record confirmation. Draft/archived details and simple projects do not generate these warnings. Saving assignments refreshes the counts; content is never assigned automatically.

The owner-scoped master summary retains `pending_projects` and adds `pending_project_assignments`: project ID/title with `overview_count` and `detail_count`. Both summary surfaces use the same shared-project pending rule as the export. Existing versioned export snapshots and historical documents are unchanged.
