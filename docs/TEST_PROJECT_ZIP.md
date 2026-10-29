# Project ZIPs, files and links

Use a disposable account and fictional project materials. No OpenAI request starts until you choose Analyze after reviewing the selected files and cost estimate.

1. Save a project without a GitHub link. Open its Project materials dialog, expand **Add ZIPs, files or pasted text**, and upload a ZIP containing Python collection scripts, Scala/Spark processing, a notebook, README and PDF/DOCX report. ZIPs and individual files may be selected together.
2. The file picker lists readable files using `archive.zip/folder/file` paths. Expand a file's Preview to inspect its extracted text. Notebook outputs are marked as historical and never rerun. Check/uncheck files; select at most 30. Uploading never modifies your Profile record or makes an AI request.
3. Add another ZIP or individual file. Existing uploads should remain available. Add a public GitHub project link: its files should appear alongside the uploads. Analyze should send just the files you selected, in one analysis. Removing uploads from the current selection must leave saved source history intact.
4. Add an ordinary http/https link, such as an AWS console project reference. It should be marked **Reference link (not read)**. The app does not log into AWS, access private storage or assume a link's contents. Provide exported code, notebooks or reports for analysis.
5. Check the limits: 32 MB total per upload; 64 MB expanded ZIP contents; 1,000 entries per archive; 10 MB per individual file; up to 300 readable uploaded preview files; 200 KB text per file and 2 MB text total. Large datasets can be left out in favor of code and a small CSV sample. Exclusions and truncation must be visible.
6. ZIP members with unsafe paths, symlinks, encryption, nested archives, binaries, dependencies, credential filenames or recognizable AWS/private-key content are excluded. Archive paths are never extracted onto disk. Document parsing may use temporary files; no project code is executed. A malformed archive should show an error without changing Profile.
7. Choose Analyze once. The preparation/progress bar should stay visible; the normal model/cost confirmation and existing request-token protection still apply. Reopening materials should load the saved snapshot/results without starting another analysis.
8. Export and restore an ordinary account backup in the disposable account. Local preview text, original file/archive names, source hashes, selected snapshot and reference links should be retained. Another account must not be able to read or select the source IDs.

Bounded extracted text and provenance are saved. Originals needing explicit OpenAI file or visual review are also retained privately and included in account backups; see TEST_PROJECT_COMMON_FILES.md. The ZIP container and excluded files are not retained. Keep your own original archive. Existing individual-file uploads and older snapshots/backups continue to work.

## Oversized uploads and transfer progress

Choose a file larger than 32 MB (or several files totaling over 32 MB). The browser must immediately show the actual total and the limit, with **Nothing was uploaded**, before any POST. An individual non-ZIP file over 10 MB and more than 30 uploads are also rejected before transfer.

For accepted files, the top bar first says **Uploading project ZIPs and files**, showing bytes/percentage when the browser supplies a total. After the transfer finishes it says **Waiting for ZIP preview**. Neither stage makes an OpenAI request. A slow transfer is distinct from waiting for the workspace to prepare the file list. Connection or Access errors must be shown without replaying the upload. Existing file selections and Profile records remain intact when an oversized selection is rejected.
