from pathlib import Path
root = Path(SPECPATH).parent
analysis = Analysis([str(root/'src/mac_service.py')], pathex=[str(root/'src')],
    datas=[(str(root/'assets'),'assets')],
    hiddenimports=['mac_platform','peer_share','mac_tunnel','ios_mobile','ApplicationServices','AppKit','Quartz','Foundation'],
    excludes=['qt_app','PySide6','matplotlib','numpy'])
pyz = PYZ(analysis.pure)
exe = EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='bridge-service',console=True,target_arch=None)
collect = COLLECT(exe,analysis.binaries,analysis.datas,name='bridge-service')
