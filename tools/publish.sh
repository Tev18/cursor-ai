#!/bin/bash
# One-time: creates a PRIVATE GitHub repository from this folder and pushes everything (with history and tags).
#   ./tools/publish.sh [repo-name]
set -e
cd "$(dirname "$0")/.."
NAME="${1:-cursor-ai}"
command -v gh >/dev/null || { echo "Install the GitHub CLI first:  brew install gh"; exit 1; }
if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub login needed. A browser window opens: sign in and click Authorize."
  gh auth login --web --git-protocol https --scopes repo,workflow
fi
OWNER="$(gh api user --jq .login)"
if git remote get-url origin >/dev/null 2>&1; then
  echo "Remote 'origin' already exists: $(git remote get-url origin)"
else
  gh repo create "$OWNER/$NAME" --private --source . --remote origin
fi
python3 tools/stamp_version.py --repo "$OWNER/$NAME"      # the app checks THIS repository for updates
if ! git diff --quiet; then
  git add mac/version.py windows/version.py
  git commit -m "Set update repository to $OWNER/$NAME"
fi
git push -u origin HEAD
git push origin --tags
echo
echo "Done: https://github.com/$OWNER/$NAME   (private)"
echo "Next: add the signing secrets (see docs/RELEASING.md), then publish with ./tools/release.sh 1.0.0"
