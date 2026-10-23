from pathlib import Path
import shutil
root = Path(SPECPATH).parent
node = Path(shutil.which('node')).resolve()
node_license = node.parent.parent/'LICENSE'
analysis = Analysis([str(root/'src/mac_service.py')], pathex=[str(root/'src'), str(root)],
    datas=[(str(root/'assets'),'assets'), (str(root/'server/desktop_agent/dsh_approval.mjs'), 'server/desktop_agent'), (str(root/'server/desktop_agent/dsh_desktop.mjs'), 'server/desktop_agent'),
           (str(root/'server/desktop_agent/skills'), 'server/desktop_agent/skills'),
           (str(root/'tools/dsh/node_modules'), 'agent-runtime/node_modules'), (str(node), 'agent-runtime')]+([(str(node_license), 'agent-runtime')] if node_license.exists() else []),
    hiddenimports=['mac_platform','peer_share','mac_tunnel','ios_mobile','rtc_bridge','connection_modes','aiortc','aioice','av','pylibsrtp','ApplicationServices','AppKit','Quartz','Foundation'],
    excludes=['qt_app','PySide6','matplotlib','numpy'])
pyz = PYZ(analysis.pure)
exe = EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='bridge-service',console=True,target_arch=None)
collect = COLLECT(exe,analysis.binaries,analysis.datas,name='bridge-service')
