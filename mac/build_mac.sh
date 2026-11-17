#!/bin/bash
# Run this ON A MAC. Produces dist/Cursor AI.app
set -e
cd "$(dirname "$0")"
if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python with Tk is required. Install Python from https://www.python.org/downloads/macos/ and retry."; exit 1
fi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pyinstaller --noconfirm --windowed --name "Cursor AI" \
  --osx-bundle-identifier com.local.cursorai \
  --hidden-import AppKit --hidden-import Foundation --hidden-import Quartz \
  --hidden-import keyring.backends.macOS \
  app.py
# Info.plist tweak is not needed; ad-hoc sign so macOS keeps permission grants stable
codesign --force --deep --sign - "dist/Cursor AI.app" || true
echo
echo "Built: dist/Cursor AI.app  (drag it to /Applications)"
echo "First launch: right-click the app > Open (it is not notarized)."
