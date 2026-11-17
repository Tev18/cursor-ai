# Releasing and updates

## 1. Create the private GitHub repository (once)
On your Mac, in this folder:
```bash
brew install gh          # if you don't have the GitHub CLI
./tools/publish.sh       # creates <you>/cursor-ai as PRIVATE and pushes history + tags
```
It opens a browser to sign in. What you authorize: **GitHub CLI (`gh`)** with the `repo` and `workflow` scopes, i.e. it can
create repositories and push code/workflows for your account. Nothing else.
(Alternative without the CLI: create an empty private repo on github.com, then
`git remote add origin https://github.com/<you>/cursor-ai.git && git push -u origin HEAD --tags`, then
`python3 tools/stamp_version.py --repo <you>/cursor-ai` and commit.)

## 2. Signing key for updates (once, recommended)
```bash
pip install cryptography && python3 tools/make_update_key.py
```
GitHub repo → **Settings → Secrets and variables → Actions**
* Secrets → `UPDATE_SIGNING_KEY` = the PRIVATE value printed
* Variables → `UPDATE_PUBLIC_KEY` = the PUBLIC value printed

Builds then embed the public key; every release zip gets a `.sig`, and installed apps refuse any update that isn't
signed by you. Without it, updates are checked for integrity (SHA-256) only.

## 3. Apple signing + notarisation (optional, needs a paid Apple Developer account)
Add these **secrets**; the workflow uses them only when all are present:

| Secret | Value |
|---|---|
| `APPLE_CERTIFICATE` | your *Developer ID Application* certificate exported as .p12, then `base64 -i cert.p12 \| pbcopy` |
| `APPLE_CERTIFICATE_PASSWORD` | the password you set when exporting the .p12 |
| `APPLE_ID` | your Apple ID email |
| `APPLE_TEAM_ID` | 10-character team ID (developer.apple.com → Membership) |
| `APPLE_APP_PASSWORD` | an app-specific password (appleid.apple.com → Sign-In and Security) |

Without them the Mac app is **ad-hoc signed and not notarised**: it works (right-click → Open the first time), but macOS
may ask you to grant Screen Recording again after each update, because the signature changes every build. A Developer ID
signature keeps the permission stable.

## 4. Private repository: letting the app read releases
Releases in a private repo are invisible without a token. In the app: **Updates → GitHub token**, paste a fine-grained
personal access token (github.com → Settings → Developer settings → Fine-grained tokens) limited to this one repository
with **Contents: Read-only**. It is stored in the Keychain / Credential Manager. (Or host releases in a public repo.)

## 5. Publish a version
Easiest: GitHub repo → **Actions** → **Release** → **Run workflow** → type the version (e.g. `1.0.0`) → Run. It creates the tag itself.
Or from the terminal:
```bash
# edit CHANGELOG.md: add  ## [1.1.0] - 2026-12-01
./tools/release.sh 1.1.0
```
Watch it with `gh run watch`. The release contains `Cursor-AI-macOS-v1.1.0.zip` (+ `.dmg`),
`Cursor-AI-Windows-v1.1.0.zip`, `SHA256SUMS.txt` and the `.sig` files.

## How an update is installed
Download (progress bar) → SHA-256 check → signature check → unpack next to the app → (macOS) `codesign --verify`, same bundle
id, Gatekeeper status shown → **you confirm** → the app quits, a helper swaps the app (backup kept until it succeeds, rolled
back on failure) and relaunches. Settings (`~/Library/Application Support/CursorAI`, `%APPDATA%\CursorAI`) and the API key
(Keychain / Credential Manager) live outside the app, so they are untouched.
The app must be somewhere you can write (e.g. `/Applications` as an admin, or `~/Applications`).
