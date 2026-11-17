# Cursor AI

Press a shortcut, mark a region of your screen with two clicks, and get Claude's answer in a small floating window.

| Folder | What |
|---|---|
| `mac/` | macOS app (Python + Tk, built with PyInstaller) |
| `windows/` | Windows app (same code base, `RegisterHotKey` shortcuts) |
| `extension/` | Chrome extension version |
| `tools/` | publishing, versioning and signing helpers |
| `.github/workflows/` | tests on every push; release builds on version tags |

Your Claude API key is stored in the macOS Keychain / Windows Credential Manager, never in this repository.

## Run or build locally
```bash
cd mac                      # or: cd windows
python3 -m pip install -r requirements.txt
python3 app.py              # run from source
./build_mac.sh              # macOS: builds dist/Cursor AI.app   (Windows: build_windows.bat)
```

## Push changes (from your Mac)
```bash
git add -A
git commit -m "Describe the change"
git push
```

## Publish a new version
1. Add a `## [1.1.0] - YYYY-MM-DD` section to `CHANGELOG.md` (it becomes the release notes).
2. `./tools/release.sh 1.1.0` bumps the version, commits, tags `v1.1.0` and pushes.
3. GitHub Actions builds the macOS and Windows apps and publishes the release. Installed apps see it under
   **Updates → Check for Updates**.

First-time setup (create the private repo, signing key, Apple credentials): see [docs/RELEASING.md](docs/RELEASING.md).

## Never commit
API keys, tokens, certificates (`.p12`, `.pem`, `.key`), `settings.json`, `api_key.txt`, `github_token.txt`.
`.gitignore` already blocks these.
