#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export LABELDESK_TESSERACT="${LABELDESK_TESSERACT:-$(brew --prefix tesseract)/bin}"
export LABELDESK_TESSDATA="${LABELDESK_TESSDATA:-$(brew --prefix)/share/tessdata}"
python3 -m pip install -r requirements-build.txt
python3 packaging/collect_licenses.py
python3 -m unittest discover -s tests -v
python3 -m PyInstaller --noconfirm --clean packaging/LabelDesk.spec
# Use a temporary local directory: synced folders may reattach Finder metadata.
stage="$(mktemp -d)/stage"
mkdir -p "$stage"
ditto --norsrc --noextattr dist/LabelDesk.app "$stage/LabelDesk.app"
xattr -cr "$stage/LabelDesk.app"
codesign --force --deep --sign - "$stage/LabelDesk.app"
codesign --verify --deep --strict "$stage/LabelDesk.app"
smoke="$(mktemp -d)/smoke"
"$stage/LabelDesk.app/Contents/MacOS/LabelDesk" --self-test "$smoke"
test -f "$smoke/PASS.txt"
ln -s /Applications "$stage/Applications"
hdiutil create -volname LabelDesk -srcfolder "$stage" -ov -format UDZO dist/LabelDesk-0.6.0-macOS-AppleSilicon.dmg
hdiutil verify dist/LabelDesk-0.6.0-macOS-AppleSilicon.dmg
