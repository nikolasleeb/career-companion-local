# Test education dates, GPA layout and import choices

Use fictional documents and a disposable account first. These controls do not run AI.

1. Open **Profile → Upload / import**, prepare two documents with a possible education/employment match, open **Resume content**, then review the education proposal’s full fields directly on the page.
2. Enter a past attendance end year directly; it must remain editable and valid for a graduated record.
3. End dates earlier than the start must show an error and cannot be saved. Unknown month/day may remain blank. **Expected graduation** keeps its separate future-date rules.
4. GPA and GPA scale should share one row on desktop and mobile. No scale is inferred: fill it only when known. Edits change only the proposal; saved Profile information changes only after final import approval.
5. For a possible match, **These sources describe the same record** and **Keep these as separate records** are two radio choices in one group. Only one can be selected. Tab and arrow keys should work.
6. Edit a contact value or a different record, then separate a pair. The pair becomes two source entries; unrelated edits, selections and match choices should remain. The final accuracy confirmation resets for the changed review.
7. Separate entries keep their original source values. If a source or saved Profile changed while you were reviewing, a fresh review replaces stale choices.
8. Cancel the review and confirm Profile is unchanged. Reopen it, review the selections and resolve differences before approving an import.

Both editions are built and checked before hosted rollout. Hosted data, settings, keys and files are backed up and preservation checked. The installed localhost service stays unchanged. Source and these instructions are pushed without a release or Git tag. Deployment does not import or delete Profile information or run paid AI.

## Typing multiple-word subjects

In both inline import review and the ordinary education editor, type a multiword major or minor character by character, including spaces. The draft must preserve spaces, new empty rows and the cursor position. Add major/minor and the final row’s Remove button share one horizontal action row on desktop and mobile; narrow layouts put that action row below a full-width input. Add a second subject, type into it, remove it and confirm the first remains intact. Empty/duplicate rows are normalized only in the approved save payload. Editing or closing import review must not save Profile information.
## Typed years

Year boxes accept typed four-digit years in all shared Profile date editors; month and optional day remain selectors. Try typing and pasting a past attendance end, a future graduation year, a partial year, an invalid year, an end before a known start, and Present/ongoing employment. Invalid/incomplete drafts must remain visible without saving a guessed year; import/save must focus the invalid year. Existing date limits and preservation rules still apply.
