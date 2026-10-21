#!/bin/zsh
# Wrap the built app in a .dmg (macOS):  packaging/make_dmg.sh <dist folder> <output.dmg>
set -e
DIST="$1"; OUT="$2"
STAGE="$(mktemp -d)"
cp -R "$DIST/Muse Monitor.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"            # drag the app onto Applications
hdiutil create -volname "Muse Monitor" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
rm -rf "$STAGE"
