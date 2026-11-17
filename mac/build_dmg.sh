#!/bin/bash
# Run ON A MAC after ./build_mac.sh. Produces dist/Cursor-AI.dmg
set -e
cd "$(dirname "$0")"
APP="dist/Cursor AI.app"
[ -d "$APP" ] || { echo "Run ./build_mac.sh first (no $APP found)."; exit 1; }
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # so users can drag the app onto it
rm -f dist/Cursor-AI.dmg
hdiutil create -volname "Cursor AI" -srcfolder "$STAGE" -ov -format UDZO dist/Cursor-AI.dmg
rm -rf "$STAGE"
echo "Built: dist/Cursor-AI.dmg"
