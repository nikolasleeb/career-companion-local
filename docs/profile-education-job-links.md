# Profile relationships and interview context


Projects use a multi-select Related education & jobs picker near the project name, replacing the new-entry course/organization field and lower job-only picker. Existing organization text remains editable in a legacy-text disclosure. Education entries can be selected independently, with courses nested under each entry. Jobs can optionally link to education and courses for academic internship credit. Associations are explicit, account-owned and validated; they do not copy accomplishments. Omitted relationship fields preserve saved links for older clients. Missing or changed destinations retain historical links and prevent new reuse until resolved. Backups validate and remap education, course and job references without a schema migration.

Non-coding interview AI payloads exclude coding language/difficulty. Question focus drafts are session-scoped, and generation instructions match the selected format while retaining relevant Profile and job context. Interview names use the highest currently saved number for the type plus one; deletion does not rename remaining sessions and old lifetime counters are ignored.

Validation uses fictional accounts, simulated providers, desktop keyboard/layout checks, backend ownership/reuse/backup tests, both frontend builds and the public-source audit. Installed localhost, releases, tags and paid user-account requests are excluded.
