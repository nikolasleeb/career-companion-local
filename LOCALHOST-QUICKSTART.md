# Run an image on localhost

1. Start current Docker Desktop or Docker Engine 28+ with Compose.
2. Download this release's `compose.localhost.yaml`, `SHA256SUMS`, and the image archive matching your architecture from the public GitHub release.
3. Verify the archive hash with `shasum -a 256 FILE` on macOS, `sha256sum FILE` on Linux, or `Get-FileHash FILE -Algorithm SHA256` in PowerShell. Compare it with `SHA256SUMS`.
4. In a terminal in the download folder, load your archive and start the app. Substitute the actual archive filename:

```sh
docker load --input career-companion-1.0.1-linux-amd64.tar.gz
docker compose -f compose.localhost.yaml up -d --pull never
```

5. Open **http://localhost:3000** and create a local account. Save your own OpenAI API key in Settings only if you want AI features.

To use a different port, place `PORT=3002` in a `.env` file beside the Compose file and open http://localhost:3002. Connect the optional browser extension to that same origin.

Stop with `docker compose -f compose.localhost.yaml stop`. Resume with `docker compose -f compose.localhost.yaml up -d --pull never`.

## Updating

Check Settings → App version & updates. Finish or save your work, then back up both named Docker volumes before updating.

Download the new release's archive and Compose file into the **same installation folder**, verify its checksum, load it with `docker load --input FILE`, and repeat the start command above. The project name and volume names stay the same. If `.env` contains a `CAREER_IMAGE` override, update it to the new version or remove that override to use the new Compose file's default.

For registry users with access to the image, use `docker compose -f compose.localhost.yaml pull` followed by `docker compose -f compose.localhost.yaml up -d` instead of loading an archive.

Never run `down -v` during an update. It deletes the volumes, including the private-disclosure recovery key. Retain the previous image and Compose file for rollback. Ordinary account exports omit sensitive private disclosures and API keys; preserving both volumes is necessary for full installation recovery.
