#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(python3 -c 'import label_parser; print(label_parser.__version__)')"
[ -n "$version" ] || { echo 'Cannot read version from label_parser/__init__.py' >&2; exit 1; }
export LABELDESK_TESSERACT="${LABELDESK_TESSERACT:-$(brew --prefix tesseract)/bin}"
export LABELDESK_TESSDATA="${LABELDESK_TESSDATA:-$(brew --prefix)/share/tessdata}"
python3 -m pip install -r requirements-build.txt
python3 packaging/collect_licenses.py
python3 -m unittest discover -s tests -v
python3 -m PyInstaller --noconfirm --clean packaging/LabelDesk.spec
# PyInstaller deduplicates dylibs by filename, and the OpenCV wheel bundles an
# older libtesseract than the Homebrew OCR binary was linked against. Give the
# OCR binary a private copy so dyld cannot bind it to OpenCV's library.
app=dist/LabelDesk.app;framework="$app/Contents/Frameworks";ocr="$framework/ocr/tesseract"
if [ -f "$ocr" ]; then
  dep="$(otool -L "$ocr" | awk '/libtesseract/{print $1;exit}')"
  brew_dep="$(brew --prefix tesseract)/lib/$(basename "${dep:-libtesseract.5.dylib}")"
  if [ -n "$dep" ] && [ -f "$brew_dep" ]; then
    private="$(basename "$dep" | sed 's/^libtesseract/libtesseract_labeldesk/')"
    cp "$brew_dep" "$framework/$private"
    chmod u+w "$framework/$private"
    install_name_tool -id "@rpath/$private" "$framework/$private"
    for lib in $(otool -L "$framework/$private" | awk 'NR>1{print $1}' | grep -E '^/(opt/homebrew|usr/local)/'); do
      install_name_tool -change "$lib" "@rpath/$(basename "$lib")" "$framework/$private"
    done
    install_name_tool -change "$dep" "@rpath/$private" "$ocr"
  fi
fi
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
hdiutil create -volname LabelDesk -srcfolder "$stage" -ov -format UDZO "dist/LabelDesk-${version}-macOS-AppleSilicon.dmg"
hdiutil verify "dist/LabelDesk-${version}-macOS-AppleSilicon.dmg"
