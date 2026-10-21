#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$TASK_ROOT"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "请在 macOS 上构建。" >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    python3.12 -m venv .venv
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements-macos.txt
else
  .venv/bin/python -m pip install -r requirements-macos.txt
fi
TASK_TEST_DATA="$(mktemp -d)"
trap 'rm -rf "$TASK_TEST_DATA"' EXIT
DOUBAO_BRIDGE_DATA_DIR="$TASK_TEST_DATA" QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest -q tests
mkdir -p build/Shengjian.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" assets/app-icon-master.png --out "build/Shengjian.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" assets/app-icon-master.png --out "build/Shengjian.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/Shengjian.iconset -o build/Shengjian.icns
.venv/bin/python -m PyInstaller --noconfirm packaging/macos.spec
TASK_ARCH="$(uname -m)"
ditto -c -k --sequesterRsrc --keepParent dist/声笺.app "dist/Shengjian-mac-${TASK_ARCH}.zip"
TASK_STAGE="$(mktemp -d "$TASK_ROOT/build/dmg-stage.XXXXXX")"
ditto dist/声笺.app "$TASK_STAGE/声笺.app"
ln -s /Applications "$TASK_STAGE/Applications"
cp docs/INSTALL-macOS.txt "$TASK_STAGE/安装说明.txt"
hdiutil create -volname "声笺" -srcfolder "$TASK_STAGE" -ov -format UDZO "dist/Shengjian-mac-${TASK_ARCH}.dmg"
echo "已生成：$TASK_ROOT/dist/声笺.app"
echo "压缩包：$TASK_ROOT/dist/Shengjian-mac-${TASK_ARCH}.zip"
echo "安装包：$TASK_ROOT/dist/Shengjian-mac-${TASK_ARCH}.dmg"
