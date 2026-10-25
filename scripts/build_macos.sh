#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TASK_ROOT"
python3 scripts/sign_macos.py
TASK_NAME="声笺"
if [[ "${SHENGJIAN_BUILD_MODE:-development}" == development ]]; then TASK_NAME="声笺开发版"; fi
[[ "$(uname -s)" == Darwin ]] || { echo '请在 macOS 构建'; exit 1; }
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null; then uv venv --python 3.12 .venv; else python3.12 -m venv .venv; fi
fi
if command -v uv >/dev/null; then uv pip install --python .venv/bin/python -r requirements-macos.txt; else .venv/bin/python -m pip install -r requirements-macos.txt; fi
.venv/bin/python -m pytest -q tests
.venv/bin/python scripts/prepare_harness.py
mkdir -p build/Shengjian.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" assets/app-icon-master.png --out "build/Shengjian.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" assets/app-icon-master.png --out "build/Shengjian.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/Shengjian.iconset -o build/Shengjian.icns
.venv/bin/python -m PyInstaller --noconfirm packaging/mac-service.spec
TASK_STAGE="$(mktemp -d "$TASK_ROOT/build/native.XXXXXX")"
TASK_APP="$TASK_STAGE/$TASK_NAME.app"
mkdir -p "$TASK_APP/Contents/MacOS" "$TASK_APP/Contents/Resources"
xcrun swiftc -O -parse-as-library native/LocalService.swift native/ShareImport.swift native/DesktopControl.swift native/ShengjianApp.swift -target arm64-apple-macos14.4 -o "$TASK_APP/Contents/MacOS/Shengjian" -framework SwiftUI -framework AppKit -framework CoreImage
cp packaging/Info-native.plist "$TASK_APP/Contents/Info.plist"
cp build/Shengjian.icns "$TASK_APP/Contents/Resources/Shengjian.icns"
TASK_EXTENSION="$TASK_APP/Contents/PlugIns/ShengjianShare.appex"
mkdir -p "$TASK_EXTENSION/Contents/MacOS" "$TASK_EXTENSION/Contents/Resources"
xcrun swiftc -O -parse-as-library -application-extension -emit-executable -module-name ShengjianShare -target arm64-apple-macos14.4 native/ShareImport.swift native/ShareExtension/ShareViewController.swift -o "$TASK_EXTENSION/Contents/MacOS/ShengjianShare" -framework AppKit -framework Foundation -Xlinker -e -Xlinker _NSExtensionMain
cp native/ShareExtension/Info.plist "$TASK_EXTENSION/Contents/Info.plist"
cp build/Shengjian.icns "$TASK_EXTENSION/Contents/Resources/Shengjian.icns"

ditto dist/bridge-service "$TASK_APP/Contents/Resources/bridge-service"
TASK_CF="$(command -v cloudflared || true)"
if [[ -z "$TASK_CF" ]]; then
  echo '构建需要 cloudflared；请从 Cloudflare 官方安装，随后重新构建。' >&2
  exit 1
fi
cp "$TASK_CF" "$TASK_APP/Contents/Resources/bridge-service/cloudflared"
cp docs/cloudflared-LICENSE "$TASK_APP/Contents/Resources/cloudflared-LICENSE"
.venv/bin/python scripts/sign_macos.py "$TASK_APP"
codesign --verify --deep --strict "$TASK_APP"
# Preserve a previous build while replacing the public artifact.
if [[ -d "dist/$TASK_NAME.app" ]]; then mv "dist/$TASK_NAME.app" "$TASK_STAGE/声笺-previous.app"; fi
mv "$TASK_APP" "dist/$TASK_NAME.app"
TASK_ARCH="$(uname -m)"
ditto -c -k --sequesterRsrc --keepParent "dist/$TASK_NAME.app" "dist/Shengjian-mac-${TASK_ARCH}.zip"
TASK_DMG="$(mktemp -d "$TASK_ROOT/build/dmg.XXXXXX")"
ditto "dist/$TASK_NAME.app" "$TASK_DMG/$TASK_NAME.app"
ln -s /Applications "$TASK_DMG/Applications"
cp docs/INSTALL-macOS.txt "$TASK_DMG/安装说明.txt"
hdiutil create -volname 声笺 -srcfolder "$TASK_DMG" -ov -format UDZO "dist/Shengjian-mac-${TASK_ARCH}.dmg"
echo "原生应用：$TASK_ROOT/dist/$TASK_NAME.app"
