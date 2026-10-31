# Evidence-planned resume optimization

An explicit first build or **Optimize for this posting** action now plans the resume before composing it. Opening a draft, its selection explanation, source drawers or exports makes no model request.

The planner receives a canonical catalog of reviewed professional facts. A linked project fact appears once, with its original experience, exact passage, revision, dates, reviewed Supporting Details and permitted destinations. Short request-local fact aliases reduce copying errors; persisted provenance uses stable source identities. Degree headers render automatically. Dense narrative sentences can become independent passages, while structured skills, courses, GPA and credentials retain canonical text.

The strategy maps quoted employer requirements, preferences, responsibilities and competencies to direct, transferable or unresolved evidence. Composition selects complementary examples and can combine passages from one original experience, preserving team boundaries, uncertainty and intent. A saved relationship permits attribution; it does not establish that every part of a project occurred during every linked job.

Optimization uses at most five model requests: strategy, composition, one editorial revision, one optional measured layout correction, and final auditing. A required comparison refresh or a separately requested chat interpretation is included in the action estimate. Provider retries are disabled for resume optimization and guided-resume actions. Account model/reasoning/tier settings, task cancellation/recovery and the usage ledger remain in effect.

The final audit sees the actual fitted document and source-backed coverage. Protected user wording and one high-value anchor per essential supported priority survive fitting. Formatting remains a readable one-page DOCX/PDF with 10.5-point body text. Conflicts preserve the previous draft and explain the problem. Invalid optional keyword suggestions are omitted rather than published; factual resume claims still require validation. Keyword inclusion uses final document text and does not predict ATS ranking or hiring outcomes.

Explicit corrections, exclusions and chosen headlines are separate from generated wording. Full optimization reconsiders selection; narrow chat refinements preserve unrelated content. Local edits create immutable rendered revisions. The collapsed selection explanation reports the focus, coverage, omissions and unresolved evidence. Local edits recompute source coverage without a paid audit; the student still reviews the exact document.

Versioned metadata is stored in existing draft/revision/conversation entities. No database migration rewrites historical documents. Account import remaps source references and derived fact identities; missing historical sources stay detached and cannot become current evidence. Cleanup discovers the nested record references through the existing recursive reference handling.

## Validation

`tests/test_resume_editorial.py` verifies document order, stable catalog indices, date handling, protected edits and factual-limit boundaries. `tests/test_resume_strategy.py` covers fictional linked contexts, exact passage composition, provenance, unsupported claims, duplicates, preserved corrections, freshness, cancellation and account import. Existing optimizer, guided-resume, role-alignment, presentation and lifecycle tests remain part of the regression suite.

The opt-in `scripts/evaluate_resume_optimization.py` compares an explicit baseline module with the new pipeline using fictional applicants. Its persisted ledger reserves a conservative estimate before dispatch, retains unknown amounts, disables retries and enforces a total ceiling of at most $12 (default $2; a larger run requires explicit authorization). The evaluator never reads real applicant records or prints a key. Results include failures, schema outputs, costs, latency and generated examples; mocked tests alone do not demonstrate provider behavior.

Official references: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Evaluation practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

The editorial revision reviews the rendered first draft against the full evidence catalog. It can replace weak content with stronger omitted examples, rank projects and bullets, and trim redundant skills/coursework. Employment and education use reverse chronology when dates are readable; unknown dates stay explicit. Source catalog indices remain stable: document order is applied after filtering, so exports and manual selections keep their provenance. The final audit checks the revised, corrected and fitted document. Local headline and content edits preserve the ranked record and bullet order in the revision catalog. Explicitly requested, confirmed skill names are retained compactly alongside applied evidence; substring matches such as Java/JavaScript do not create skill evidence. A measured correction may remove short carryover lines after editing, without changing selection or user locks.

## Structured path

1. Read the posting's professional requirements, preferences and responsibilities. Administrative/private eligibility stays separate.
2. Map confirmed education, work, projects, skills and reviewed Supporting Details to those priorities. GPA is useful when requested, when it establishes an explicit threshold, or when it strengthens relevant education; there is no blanket cutoff. Courses earn space through relevance.
3. Select complementary evidence and write source-backed bullets, preserving individual contribution and scope. The existing review-first resume question flow can clarify useful missing details; unapproved answers never become resume facts.
4. Review the rendered draft for substance, order, concise writing and compact relevant skill labels, then correct measured layout problems if needed.
5. Fit one readable page and audit the actual final document, preserving user constraints and source freshness.

The planner's Automatic output allowance is 32,000 tokens for High, XHigh and Max reasoning. Explicit account output limits still apply. A failed or incomplete request is never automatically repeated.
