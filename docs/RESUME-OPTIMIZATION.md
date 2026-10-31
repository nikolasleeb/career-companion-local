# Evidence-planned resume optimization

An explicit first build or **Optimize for this posting** action now plans the resume before composing it. Opening a draft, its selection explanation, source drawers or exports makes no model request.

The planner receives a canonical catalog of reviewed professional facts. A linked project fact appears once, with its original experience, exact passage, revision, dates, reviewed Supporting Details and permitted destinations. Short request-local fact aliases reduce copying errors; persisted provenance uses stable source identities. Degree headers render automatically. Dense narrative sentences can become independent passages, while structured skills, courses, GPA and credentials retain canonical text.

The strategy maps quoted employer requirements, preferences, responsibilities and competencies to direct, transferable or unresolved evidence. Composition selects complementary examples and can combine passages from one original experience, preserving team boundaries, uncertainty and intent. A saved relationship permits attribution; it does not establish that every part of a project occurred during every linked job.

Optimization uses at most four model requests: strategy, composition, one optional measured layout correction, and final auditing. A required comparison refresh or a separately requested chat interpretation is included in the action estimate. Provider retries are disabled for resume optimization and guided-resume actions. Account model/reasoning/tier settings, task cancellation/recovery and the usage ledger remain in effect.

The final audit sees the actual fitted document and source-backed coverage. Protected user wording and one high-value anchor per essential supported priority survive fitting. Formatting remains a readable one-page DOCX/PDF with 10.5-point body text. Conflicts preserve the previous draft and explain the problem. Invalid optional keyword suggestions are omitted rather than published; factual resume claims still require validation. Keyword inclusion uses final document text and does not predict ATS ranking or hiring outcomes.

Explicit corrections, exclusions and chosen headlines are separate from generated wording. Full optimization reconsiders selection; narrow chat refinements preserve unrelated content. Local edits create immutable rendered revisions. The collapsed selection explanation reports the focus, coverage, omissions and unresolved evidence. Local edits recompute source coverage without a paid audit; the student still reviews the exact document.

Versioned metadata is stored in existing draft/revision/conversation entities. No database migration rewrites historical documents. Account import remaps source references and derived fact identities; missing historical sources stay detached and cannot become current evidence. Cleanup discovers the nested record references through the existing recursive reference handling.

## Validation

`tests/test_resume_strategy.py` covers fictional linked contexts, exact passage composition, provenance, unsupported claims, duplicates, preserved corrections, freshness, cancellation and account import. Existing optimizer, guided-resume, role-alignment, presentation and lifecycle tests remain part of the regression suite.

The opt-in `scripts/evaluate_resume_optimization.py` compares an explicit baseline module with the new pipeline using fictional applicants. Its persisted ledger reserves a conservative estimate before dispatch, retains unknown amounts, disables retries and enforces a total ceiling of at most $2. The evaluator never reads real applicant records or prints a key. Results include failures, schema outputs, costs, latency and generated examples; mocked tests alone do not demonstrate provider behavior.

Official references: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Evaluation practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
