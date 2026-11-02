# Browser installation and validation boundaries

## Chrome

1. Download `career-companion-chrome.zip` from Application Assistant or `extensions/packages/`.
2. Unzip it into a permanent local folder, such as `~/Applications/Career Companion Extensions/chrome`. Keep it there: Chrome loads the files directly. Deleting or moving that folder causes `ERR_FILE_NOT_FOUND`.
   If updating, replace the files in that same folder and use **Reload** in `chrome://extensions`. Moving to a different folder can change the extension identity and require pairing again.
3. Open `chrome://extensions`, enable Developer mode, select **Load unpacked** and select the unzipped folder.
4. Open Career Companion in the same browser. Local addresses include `http://localhost:3000` or `http://127.0.0.1:3000`. The configured future hosted address is `https://career-companion.austrich-server.com`.
5. In the popup, enter the exact app origin and select **Connect this browser**. Approve the browser's requested permission for that app origin yourself. Match the code in the popup to the code in Application Assistant before approving pairing.
6. Keep that signed-in app tab open. Return to the employer form, activate the extension again, load the application list, choose the exact saved versions and approve disclosure.

Only `activeTab`, `scripting` and `storage` are required. Optional host access is restricted to localhost/127.0.0.1 and the configured hosted origin. Employer access is scoped to explicit activation; no blanket access to all browsing is requested. The popup works without Chrome side panels.

The owner granted the native app-origin permission. Installed Chrome 1.0.1 passed the complete fictional localhost workflow, manual PDF attachment, dynamic/repeated fields and seven zero-write boundary cases. Installed 1.0.2 then passed Enter-to-connect and a four-write multipage popup regression; engine/background/relay bytes are unchanged. Hosted-origin pairing remains a separate acceptance check.

## Safari on macOS

Release 1.0.12 includes a universal Safari app ZIP containing a Developer ID-signed, notarized and stapled app, plus `career-companion-safari.zip` containing the matching WebExtension source. The browser core version is 1.0.9; the app release version is independent.

1. Download `career-companion-safari-1.0.9-macos-universal.zip` and verify its SHA-256 against the release checksums.
2. Extract the ZIP, move Career Companion.app to Applications and open it. In Safari Settings → Extensions, enable Career Companion and approve only the needed app and active employer-site permissions.
3. Pair explicitly with the signed-in Career Companion tab by comparing the code. Installation never starts filling or shares documents.

The wrapper source is in `extensions/safari-xcode/`. To reproduce a distribution, commit the exact clean source and run:

```sh
python3 scripts/package_safari.py --identity 'Developer ID Application: YOUR IDENTITY' --team YOURTEAM --notary-profile YOUR_KEYCHAIN_PROFILE --output /tmp/career-safari-distribution
```

Use your legitimate Developer ID Application certificate and existing notarytool Keychain profile. Signing credentials are never included in source or downloads. The script builds both Apple Silicon and Intel binaries, compares embedded resources with the Safari ZIP, notarizes/staples the app and DMG, and requires Gatekeeper acceptance. Omitting the profile prepares a signed candidate only and exits with a publication blocker; it does not claim notarization. The script does not install the app or change Safari settings.

A Development-signed Xcode build is suitable for its existing development installation and is separate from the notarized distribution. The earlier installed 1.0.9 update was Development-signed; this release does not replace that installed copy automatically. New installer acceptance on additional Macs remains separate from shared Chromium/WebKit fixture testing.

## Form behavior

Supported: native text/email/tel/URL/number/date/textarea controls, selects, radio groups, checkboxes, visible accessible combobox options, existing repeated education/employment fieldsets and dynamically added groups after rescanning.

Manual handoffs: file picker uploads, custom/inaccessible controls, inaccessible frames, ambiguous navigation, adding experience groups where the site lacks an understood structure, and unresolved questions. The assistant does not upload a guessed path or silently select another document. It downloads only the selected approved saved PDF; changed versions require a new run.

Stops: login, CAPTCHA, signatures, attestations, payments, final submission controls, repeated page signatures, stalled navigation and unchanged validation errors. Navigation only clicks a unique literal Next/Continue/Save and continue control and rejects detectable final/cross-origin form actions. Review the destination personally when its semantics are uncertain.

Runs last at most one hour, 20 pages and 300 writes. Reopening a popup never starts a paid action. Server/browser restarts pause the run. Session changes and revocation block further writes, and transient private values are cleared.

## Fictional acceptance checklist

Serve `extensions/fixtures/` locally, using a separate test account and saved fictional documents. Confirm:

- Native fields, options, radio/checkbox choices and visible combobox values pass readback.
- A manually typed value, changed option definition or post-scan edit is preserved.
- Repeated education/employment entries use the intended records; unknown layouts pause.
- Ordinary Next progresses; final submission, CAPTCHA, login and signature never run automatically.
- Uploads use the approved version via a manual picker.
- Revoking pairing, logging out, switching accounts or changing website origin stops the run.
- Both localhost and hosted origin pair independently, once the hosted deployment is available.

Automated fixtures: `extensions/tests/browser-engine.cjs` (Chromium + WebKit), `relay-security.cjs`, and `extension-integration.cjs` (unmodified Chrome package; requires native permission interaction). Keep their scope distinct in validation reports.

## Rerunning automated browser checks

Install Playwright in your chosen test environment and make its module available through normal Node resolution or `PLAYWRIGHT_MODULE=/absolute/path/to/playwright`. Install its Chromium/WebKit browsers and set `PLAYWRIGHT_BROWSERS_PATH` if using a custom cache. Then run:

```sh
node extensions/tests/relay-security.cjs
node extensions/tests/connection-origins.cjs
node extensions/tests/browser-engine.cjs
```

`app-workflow.cjs` additionally needs an isolated loopback server on port 3100 and fictional data created by `scripts/seed_assistant_demo.py` under `qa/browser-data`. The seed refuses production mode and directories outside `qa`; start the test app once before seeding. Never point these tests at the real account database. `extension-integration.cjs` loads the unmodified package into a new test profile and reports a blocker if native optional-origin permission does not complete.


## Extension 1.0.6: reconnect after app-tab refresh

Refreshing the signed-in Career Companion tab now restores its connection script automatically, using the exact paired tab and origin. Reopening the popup can reload Applications without starting or resuming filling. A closed tab, changed account, expired login or revoked permission still needs your attention; open and sign in to Career Companion, then use Connect this browser. Filling resumes only after your explicit action.

For Chrome, replace the files in your existing unpacked extension folder with the updated package, then select Reload in chrome://extensions once. Keep your employer form open; do not submit it as part of connection recovery.


## Application filling 1.0.9

The assistant processes supported empty fields in visual page order, then lists the remaining items. Passwords, verification, signatures, acknowledgements, uploads and unsupported controls stay on the employer page. Other questions can be reviewed in Career Companion. Existing values are preserved; obvious placeholders such as Unknown are flagged for your review. Mixed registration pages no longer block routine fields solely because a password appears farther down. The extension never reads or fills passwords, accepts terms, creates an employer account, or submits an application. Advance registration and protected pages personally, then explicitly Resume filling on the employer tab.

Use the updated hosted app with package 1.0.9. Older extension scans retain their prior stop behavior. Updating/reloading the extension can clear pairing; reconnect and approve the matching code yourself before starting or resuming. No update starts filling automatically.


### Searchable menus and repeated history rows

Package 1.0.9 supports Select2 School and Employer menus using exact available choices. Recognized Add Another controls create up to ten saved education or employment rows per section. Existing occupied rows are matched before empty slots are assigned; ambiguous records and unavailable choices remain in the review list. No Remove or submission control is used to expand history. Saved authorization/sponsorship follows the matching rules in [Personal Details](PERSONAL-DETAILS.md); other private disclosures retain review requirements.

An existing Xcode Apple account can notarize through Organizer without a separate command-line Keychain profile. Archive the macOS app for both architectures, choose **Distribute App → Direct Distribution**, wait for notarization success, then Export. Package that export with:

```sh
python3 scripts/package_safari.py --notarized-app '/path/to/Career Companion.app' --output /tmp/career-safari-distribution
```

This path verifies Developer ID signatures, matching bundled extension resources, both architectures, the app's stapled ticket and Gatekeeper acceptance. It extracts the resulting ZIP and repeats those checks. Notarization applies to the contained app; the ZIP is its transport archive. A DMG built separately needs its own notarization before it can be advertised as a notarized DMG.
