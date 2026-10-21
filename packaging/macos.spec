from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'src' / 'qt_app.py')],
    pathex=[str(root / 'src')],
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=['mac_platform', 'ApplicationServices', 'AppKit', 'Quartz', 'Foundation'],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'matplotlib', 'numpy'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='Shengjian',
          console=False, target_arch=None, codesign_identity=None, entitlements_file=None)
collect = COLLECT(exe, analysis.binaries, analysis.datas, name='Shengjian')
app = BUNDLE(collect, name='声笺.app', icon=str(root / 'build' / 'Shengjian.icns'),
             bundle_identifier='com.doubaolaninputbridge.mac',
             info_plist={
                 'CFBundleName': '声笺',
                 'CFBundleDisplayName': '声笺',
                 'CFBundleShortVersionString': '1.0.0',
                 'CFBundleVersion': '1',
                 'NSHighResolutionCapable': True,
                 'LSMinimumSystemVersion': '14.4',
                 'NSLocalNetworkUsageDescription': '让同一 Wi-Fi 的手机通过扫码与 Mac 互传文字、图片和文件。',
                 'NSAccessibilityUsageDescription': '将手机发送的内容通过 ⌘V 粘贴到你当前选中的输入框。',
                 'NSHumanReadableCopyright': 'Based on qinze889/DoubaoLanInputBridge; macOS local adaptation.',
             })
