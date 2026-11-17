#!/bin/bash
# Publishes a new version:  ./tools/release.sh 1.1.0
# Bumps the version in both apps, commits, tags v1.1.0 and pushes; GitHub Actions then builds and publishes the release.
set -e
cd "$(dirname "$0")/.."
V="${1:?usage: ./tools/release.sh 1.2.3}"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]] || { echo "Version must look like 1.2.3"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "Commit or stash your changes first."; exit 1; }
grep -q "^## \[$V\]" CHANGELOG.md || { echo "Add a '## [$V] - $(date +%F)' section to CHANGELOG.md first (it becomes the release notes)."; exit 1; }
git rev-parse "v$V" >/dev/null 2>&1 && { echo "Tag v$V already exists."; exit 1; }
python3 tools/stamp_version.py --version "$V"
git add mac/version.py windows/version.py
git commit -m "Release v$V" --allow-empty
git tag -a "v$V" -m "Cursor AI v$V"
git push origin HEAD
git push origin "v$V"
echo "Pushed v$V. Watch the build: gh run watch   (or the Actions tab on GitHub)"
