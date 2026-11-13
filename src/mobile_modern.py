"""Shared clean and responsive phone layout for Windows and Mac bridge pages.

Applied after the existing mobile document so the message and upload contracts remain
untouched. The CSS deliberately has no remote dependencies or fixed viewport widths.
"""

STYLE = r"""
<style id="shengjian-mobile-modern">
:root {
  --bg: #f6f8fc;
  --panel: #fff;
  --panel-soft: #fff;
  --text: #172033;
  --muted: #667085;
  --line: #e5e9f2;
  --accent: #2563eb;
  --accent-strong: #1d4ed8;
  --secondary: #eef3ff;
  --ok: #14804a;
  --shadow: 0 8px 34px rgba(33, 47, 77, .055);
  --soft-shadow: 0 3px 13px rgba(33, 47, 77, .04);
}
html, body { width: 100%; min-width: 0; max-width: 100%; overflow-x: clip; }
body {
  background: #f6f8fc !important;
  padding: max(20px, env(safe-area-inset-top)) max(14px, env(safe-area-inset-right))
           max(22px, env(safe-area-inset-bottom)) max(14px, env(safe-area-inset-left));
  -webkit-font-smoothing: antialiased;
}
.visual-backdrop, .visual-backdrop::before, .visual-backdrop::after { display: none !important; animation: none !important; }
.app-shell { width: min(100%, 700px) !important; min-width: 0; max-width: 700px; gap: 16px; margin: 0 auto; animation: none !important; }
.app-shell > *, .tool-card > *, .input-drawer, .send-panel,
.mobile-tool-switches, .file-tools, .file-row, .prompt-workbench,
.quick-actions, .shared-files-panel { min-width: 0; max-width: 100%; }
.mobile-brand { display: flex; align-items: center; gap: 12px; padding: 8px 2px 5px; min-width: 0; }
.mobile-mark {
  width: 44px; height: 44px; border-radius: 14px; display: grid; place-items: center; flex-shrink: 0;
  background: #2563eb; color: white; font-size: 26px; font-weight: 700;
  box-shadow: 0 8px 18px rgba(37, 99, 235, .12);
}
.mobile-brand-copy { display: grid; gap: 2px; flex: 1; min-width: 0; }
.mobile-brand-copy strong { font-size: 22px; font-weight: 760; letter-spacing: -.5px; }
.mobile-brand-copy small { color: #667085; font-size: 12px; line-height: 1.4; }
.mobile-connected {
  display: flex; align-items: center; gap: 6px; white-space: nowrap;
  border-radius: 999px; padding: 6px 9px; color: #14804a; background: #eaf7f0;
  font-size: 11px; font-weight: 600; flex-shrink: 0;
}
.mobile-connected::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tool-card {
  gap: 18px; border: 1px solid var(--line) !important; border-radius: 22px !important;
  padding: 22px !important; background: #fff !important; box-shadow: var(--shadow) !important;
  backdrop-filter: none !important;
}
.editor-title strong { font-size: 17px; font-weight: 740; }
.editor-title span { color: #768095; font-size: 12px; line-height: 1.6; }
.drawer-summary { align-items: center; }
textarea, .compact-input {
  display: block; width: 100% !important; max-width: 100%; min-width: 0;
  border: 1px solid #dde4ee !important; border-radius: 15px !important;
  background: #f8fafc !important; color: #172033 !important;
  -webkit-text-fill-color: #172033 !important;
  box-shadow: none !important; padding: 15px !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px !important; line-height: 1.6; overflow-wrap: anywhere; word-break: break-word;
}
.compact-input { min-height: 184px; }
textarea:focus { background: white !important; outline: 3px solid #2563eb1a !important; border-color: #3b82f6 !important; }
.mobile-tool-switches { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
button { max-width: 100%; min-width: 0; border-radius: 12px !important; background: #2563eb; box-shadow: none !important; font-weight: 650; }
button:hover { box-shadow: none !important; }
.ghost-button, button.secondary, .tool-toggle {
  color: #2b4b86 !important; background: #eef3ff !important; border: 1px solid #dfe8fb !important;
}
.tool-toggle { min-height: 47px; font-size: 13px; }
.tool-toggle.active { background: #e6edff !important; border-color: #bcd0fa !important; color: #1d4ed8 !important; }
.primary-action, #send { background: #2563eb !important; border: 1px solid #2563eb !important; color: #fff !important; }
.send-panel { grid-template-columns: minmax(0, 1fr) auto; gap: 15px; padding-top: 15px; border-top: 1px solid var(--line); }
.option-grid, .checks { min-width: 0; }
.checks label { min-width: 0; white-space: normal; font-size: 12px; }
.message { font-size: 13px; }
.file-tools, .prompt-workbench {
  padding: 14px !important; border: 1px solid var(--line) !important;
  border-radius: 16px !important; background: #fafbfe !important;
}
.file-dropzone, .shared-file-link, .shared-text-item { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.file-dropzone { background: #fff; border-color: #cbd7eb; }
.file-list, .file-copy, .shared-file-copy, .shared-text-content { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.prompt-tools, .file-action-row, .action-row, .prompt-actions { min-width: 0; max-width: 100%; }
select, input[type=number] { min-width: 0; max-width: 100%; }
.mobile-hint { color: #8a92a3; text-align: center; font-size: 12px; line-height: 1.65; padding: 0 14px; }
@media (max-width: 600px) {
  body { padding: max(12px, env(safe-area-inset-top)) max(12px, env(safe-area-inset-right))
                max(16px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left)); }
  .app-shell { gap: 12px; }
  .mobile-brand { gap: 9px; }
  .mobile-mark { width: 40px; height: 40px; font-size: 23px; border-radius: 12px; }
  .mobile-brand-copy strong { font-size: 20px; }
  .mobile-connected { padding: 5px 7px; font-size: 10px; }
  .tool-card { padding: 14px !important; border-radius: 18px !important; gap: 15px; }
  .drawer-summary { align-items: flex-start; gap: 10px; }
  .drawer-summary .ghost-button { flex: 0 0 auto; align-self: flex-start; }
  .editor-title strong { font-size: 16px; }
  .editor-title span { font-size: 11px; }
  textarea, .compact-input { min-height: 172px; font-size: 16px !important; }
  .input-drawer.input-expanded .compact-input { min-height: 245px; }
  .quick-actions, .send-panel, .file-row, .editor-head { grid-template-columns: minmax(0, 1fr); }
  .send-panel { gap: 12px; }
  .send-panel .action-row { display: grid; grid-template-columns: minmax(0,1fr); width: 100%; }
  .send-panel .action-row > button { width: 100%; min-height: 52px; }
  .mobile-tool-switches button { width: 100%; white-space: normal; }
  .file-action-row { justify-content: stretch; }
  .file-action-row > button { flex: 1 1 100px; }
  .prompt-tools label { flex-wrap: wrap; }
  .prompt-tools select { width: min(100%, 210px); }
  .mobile-hint { font-size: 11px; padding: 0 8px; }
}
@media (max-width: 340px) {
  .mobile-connected { font-size: 0; padding: 8px; }
  .mobile-connected::before { width: 7px; height: 7px; }
  .mobile-brand-copy small { font-size: 11px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
"""

BRAND = """
<header class="mobile-brand">
  <span class="mobile-mark" aria-hidden="true">〽</span>
  <div class="mobile-brand-copy"><strong>声笺</strong><small>输入文字，直接发送到电脑</small></div>
  <span class="mobile-connected">已连接</span>
</header>
"""


def apply(page: str) -> str:
    """Keep all existing mobile API, controls and element IDs unchanged."""
    if '<main class="app-shell">' not in page or '</head>' not in page:
        raise ValueError('未找到声笺手机页面布局')
    return page.replace('</head>', STYLE + '</head>', 1).replace(
        '<main class="app-shell">', '<main class="app-shell">' + BRAND, 1
    ).replace(
        '</main>', '<p class="mobile-hint">先在电脑上选中目标输入框，再发送内容。</p></main>', 1
    )
