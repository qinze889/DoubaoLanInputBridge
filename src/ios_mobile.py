"""iOS typography, grouped surfaces and controls for the existing phone workflow."""
STYLE = '''
<style id="ios-appearance">
:root { --text:#1d1d1f; --muted:#86868b; --primary:#007aff; --border:#e5e5ea; --shadow:none; --soft-shadow:none; font-family:-apple-system,BlinkMacSystemFont,sans-serif; }
body { background:#f2f2f7!important; padding: max(20px,env(safe-area-inset-top)) 18px max(24px,env(safe-area-inset-bottom)); -webkit-font-smoothing:antialiased; }
.visual-backdrop { display:none!important; }
.ios-brand { padding:8px 4px 24px; } .ios-brand h1 { margin:0 0 8px; } .ios-brand p { margin:0; font-size:14px; color:#86868b; } .ios-brand .ios-online { font-size:11px; color:#248a3d; background:#34c75914; border-radius:20px; padding:5px 10px; float:right; margin-top:8px; }
.app-shell,main { max-width:680px!important; margin:auto; animation:none!important; }
.hero,.hero-card,.brand,.page-header { background:transparent!important; box-shadow:none!important; border:0!important; padding-left:4px; }
h1 { font-size:34px!important; line-height:1.15!important; letter-spacing:-1.2px; font-weight:750!important; }
.panel,section,.input-drawer,.file-tools,.prompt-workbench,.shared-files-panel { border-radius:24px!important; box-shadow:none!important; border:0!important; background:#fff!important; }
.panel { padding:22px!important; }
textarea { background:#f5f5f7!important; color:#1d1d1f!important; -webkit-text-fill-color:#1d1d1f!important; border:0!important; border-radius:18px!important; font:17px/1.65 -apple-system,BlinkMacSystemFont,sans-serif!important; padding:18px!important; box-shadow:none!important; }
textarea:focus { outline:2px solid #007aff33!important; }
button { border:0!important; border-radius:14px!important; min-height:42px; background:#f2f2f7!important; color:#007aff!important; font:600 15px -apple-system,BlinkMacSystemFont,sans-serif!important; box-shadow:none!important; }
#send,#acceptPromptResult { background:#007aff!important; color:#fff!important; border-radius:17px!important; min-height:54px; font-size:17px!important; }
button:active { transform:scale(.98); opacity:.82; }
.checks { display:flex; gap:20px; flex-wrap:wrap; }
.checks label { display:flex; gap:8px; align-items:center; font-size:13px!important; color:#636366; }
input[type=checkbox] { appearance:none; -webkit-appearance:none; width:38px; height:23px; border-radius:20px; background:#e5e5ea; position:relative; transition:background .2s; flex-shrink:0; }
input[type=checkbox]:checked { background:#34c759; }
input[type=checkbox]::after { content:''; position:absolute; width:19px; height:19px; border-radius:50%; top:2px; left:2px; background:white; box-shadow:0 1px 3px #0002; transition:transform .2s; }
input[type=checkbox]:checked::after { transform:translateX(15px); }
.file-dropzone { border:1.5px dashed #d1d1d6!important; border-radius:20px!important; background:#f9f9fb!important; }
.shared-file-link,.shared-text-item { background:#f5f5f7!important; border:0!important; border-radius:16px!important; }
.message { border-radius:14px!important; font-size:14px!important; }
@media(prefers-color-scheme:dark) {
:root { --text:#f5f5f7; --muted:#98989d; --border:#38383a; }
body { background:#000!important; color:#f5f5f7!important; }
.panel,section,.input-drawer,.file-tools,.prompt-workbench,.shared-files-panel { background:#1c1c1e!important; }
textarea { background:#2c2c2e!important; color:#fff!important; -webkit-text-fill-color:#fff!important; }
button,.shared-file-link,.shared-text-item { background:#2c2c2e!important; }
.file-dropzone { background:#2c2c2e!important; border-color:#48484a!important; }
}
@media(prefers-reduced-motion:reduce) { * { animation:none!important; transition:none!important; } }
</style>
'''


def apply(page):
    page = page.replace('</head>', STYLE+'</head>', 1)
    page = page.replace('<main class="app-shell">', '<main class="app-shell"><header class="ios-brand"><span class="ios-online">● 已连接到 Mac</span><h1>声笺</h1><p>随手说，随处写。</p></header>', 1)
    return page
