# Learning resources and Action Plans

Explore Occupations compares occupations, published wages and skill information.
Action Plans holds reviewed timelines, version history, milestone/step checklists
and plan-specific conversations. Skills finds resources and focused practice;
selecting topics and following milestone links uses no AI.

## Topic suggestions

`/api/skills/options` retains legacy string suggestions and adds structured
`suggested_topics` with canonical IDs, labels and source references. Posting
mentions rank first, then explicit skill goals or resolved occupation requirements,
then explicit confirmed Profile skills. Established aliases merge; resource
availability and occupational importance break ties. Field filters apply to
suggestions and resources. Generic catalog tags are not learning skills.

The shared learning vocabulary combines concrete curated topics with published
O*NET skills. It never infers a deficiency, qualification or regulated eligibility.
Unreviewed records, private answers and raw Work Styles answers are not inputs.
Career Goals and personal context sent to AI retain their existing sharing rules.

## Saved suggestions and links

`POST /api/preparation` accepts neutral `selected_topics`; legacy `confirmed_gaps`
is accepted as selected interests, not a verified gap. AI returns at most three
standalone activities and five existing resource IDs. Unknown IDs fail without
replacing previous saved suggestions or automatically retrying. Browsing, resource
filtering and preparing an unsent Action Plans draft do not run AI.

Milestones may include up to five `learning_topics`. These can be reviewed and
edited before saving. Missing fields in old plans are projected from explicit
recognized names in titles/steps, without rewriting records. An explicit empty
list suppresses links. Topic metadata does not enter checklist step identities.
`GET /api/skills/plan-link` verifies ownership of the plan and milestone before
returning the originating chat/version. Topic links and Back to this milestone
retain the exact plan version and never mark anything complete.

The visible names changed while existing `#/career-explorer`, `#/career-plans`
and `#/skills` routes, account data, backups and unsent drafts remain compatible.
The extra-subject textbox is removed; old saved values appear read-only with an
explicit Remove additional subjects action so no hidden filter is applied.

## Desktop acceptance checks

1. Open Explore Occupations: confirm the extra-subject box is gone and both
   Profile selectors still expand and retain choices.
2. Open Skills: confirm concrete topic names and source labels. Select SQL and
   inspect Codecademy/DataCamp cards and access information. With no topic filter,
   inspect University of Arizona Center for Career Readiness under Career support.
3. Open a saved Action Plan with SQL/Python in a milestone. Select Learn SQL,
   reload Skills, then Back to this milestone. Confirm the same version and
   checkbox progress. Older plans derive links only for recognized explicit names.
4. Add an uncatalogued topic: confirm the resource empty state does not invent a
   provider. Check that existing chats, plans and saved searches still open.
5. Optional paid test: request practice suggestions for SQL, then Plan these
   suggestions in Action Plans. Check the new draft is unsent. Generate a proposal,
   edit its Learning topics, save, and test the links. Each AI button uses your
   normal API setup and estimated usage; browsing and navigation are free.

No installed-localhost update, release/tag, mobile verification or paid request on
the real user's account is part of this delivery.
