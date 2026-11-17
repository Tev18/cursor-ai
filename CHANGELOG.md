# Changelog

All notable changes to Cursor AI. Format follows [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/). Each `## [x.y.z]` section becomes the release notes on GitHub.

## [1.0.3] - 2026-11-17
### Fixed
- Screenshot quality: selected regions are no longer shrunk to 1568 px. The limit is now 2576 px on the long edge, so Retina/high-DPI text stays sharp (only very large regions are scaled, and always kept under the API's 5 MB limit).

## [1.0.2] - 2026-11-17
### Added
- **Popup Size** slider (50%–150%) in Appearance: scales the answer popup and its text together. Saved with your settings.

## [1.0.1] - 2026-11-17
### Fixed
- Mouse wheel and trackpad scrolling in the settings window (it threw an error instead of scrolling); also handles Tk 9 trackpad events.
- Update check failing with `CERTIFICATE_VERIFY_FAILED` on macOS Python (now trusts the certifi CA bundle).
- App icon (gold rounded square with a pointer) for the macOS app and the Windows exe.

## [1.0.0] - 2026-11-17
First tagged release of the desktop apps.

### Added
- **Black-and-gold interface** for the macOS and Windows apps: rounded cards, buttons, fields, dropdown, slider and
  switch with hover animations; compact layout that fits on one screen.
- **Updates** card: installed/latest version, *Check for Updates*, *Install Update*, status indicator, download progress,
  release notes and an automatic-check switch. Updates come from GitHub Releases, are verified (SHA-256 and an
  Ed25519 publisher signature when the build has a key; code-signature check on macOS), need your confirmation, keep your
  settings and API key, and relaunch the app. Optional GitHub token for private repositories.
- **API key field is always visible**: the saved key loads from the Keychain / Credential Manager, masked, with a
  Show/Hide toggle. It re-masks whenever the window is reopened.
- Popup opacity slider 10%–100% in 1% steps (85% on new installs) and an **Always on Top** switch.
- Keyboard shortcut buttons that record the next key combination (shown with ⌃ ⌥ ⇧ ⌘ on macOS), conflict detection.
- macOS Screen Recording status and shortcut button; Input Monitoring is no longer shown (shortcuts use Carbon hotkeys).
- Windows app with the same features (global hotkeys via `RegisterHotKey`).
- GitHub Actions: tests on every push; tagged pushes build, sign, (optionally) notarise and publish releases.

### Changed
- Settings moved to a single `SettingsStore` for secrets (API key, optional GitHub token) with Keychain/Credential Manager first.

### Earlier (before versioning)
- Chrome extension; two-click region selection; transparent, pinned answer popup; global hotkeys; text-colour hotkey;
  larger token budget with automatic retry.
