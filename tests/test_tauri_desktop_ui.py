from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "desktop" / "src" / "App.tsx"
APP_STYLES = ROOT / "desktop" / "src" / "App.css"


def test_visible_brand_is_shengjian_while_internal_identity_stays_compatible():
    source = APP_SOURCE.read_text(encoding="utf-8")
    config = (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    rust_source = (ROOT / "desktop" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    service_source = (ROOT / "src" / "gui_app.py").read_text(encoding="utf-8")

    assert '<strong>声笺</strong>' in source
    assert "声笺 {update.version}" in source
    assert '"productName": "声笺"' in config
    assert '"title": "声笺"' in config
    assert '"identifier": "com.qinze.doubao-lan-input-bridge"' in config
    assert '.title("声笺")' in rust_source
    assert '.tooltip("声笺")' in rust_source
    assert 'APP_NAME = "声笺"' in service_source
    assert 'APP_ID = "DoubaoLanInputBridge"' in service_source


def test_brand_rename_keeps_old_install_location_upgradeable():
    config = (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    hooks = (ROOT / "desktop" / "src-tauri" / "windows" / "installer-hooks.nsh").read_text(encoding="utf-8")
    rust_source = (ROOT / "desktop" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert '"installerHooks": "windows/installer-hooks.nsh"' in config
    assert "NSIS_HOOK_PREINSTALL" in hooks
    assert r"Software\qinze\豆包语音输入桥" in hooks
    assert "StrCpy $INSTDIR" in hooks
    assert "SetOutPath $INSTDIR" in hooks
    assert "NSIS_HOOK_POSTINSTALL" in hooks
    assert r"Uninstall\豆包语音输入桥" in hooks
    assert "std::env::current_exe()" in rust_source


def test_opening_qr_refreshes_network_address_after_adapter_changes():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "const openQrDialog = async () =>" in source
    assert "await loadBridgeState()" in source
    assert "onClick={() => void openQrDialog()}" in source


def test_history_category_filter_uses_full_hit_area_buttons():
    source = APP_SOURCE.read_text(encoding="utf-8")
    styles = APP_STYLES.read_text(encoding="utf-8")

    assert 'className="category-tabs"' in source
    assert "aria-pressed={category === value}" in source
    assert "onClick={() => setCategory(value)}" in source
    assert "<select" not in source
    assert ".category-tabs button" in styles
    assert "justify-content: center" in styles


def test_history_title_is_short_and_consistent():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert '<span>史记</span>' in source
    assert '<h1 className="history-title">史记</h1>' in source
    assert "语音桥历史" not in source


def test_manage_tools_use_real_result_endpoints_and_show_status():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "'/desktop/diagnostics/copy'" in source
    assert "result.characters" in source
    assert "result.allowed" in source
    assert "toolResult" in source


def test_file_row_folder_button_opens_containing_directory_not_default_app():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "const openRecordFolder" in source
    assert "mode: 'folder'" in source
    assert "record.type === 'text' ? activateRecord(record) : openRecordFolder(record)" in source
    assert "打开所在目录" in source


def test_history_heading_uses_compact_ink_banner_without_helper_copy():
    source = APP_SOURCE.read_text(encoding="utf-8")
    styles = (ROOT / "desktop" / "src" / "App.css").read_text(encoding="utf-8")

    assert "本机内容归档" not in source
    assert "双击文字复制，双击文件使用默认应用打开。" not in source
    assert 'className="history-banner"' in source
    assert 'className="history-title"' in source
    assert 'className="history-seal"' in source
    assert ".history-banner" in styles
    assert "background: #10241f" in styles
    assert ".history-title" in styles
    assert 'font-family: "STXingkai"' in styles
    assert "font-size: 40px" in styles
    assert ".history-seal" in styles


def test_history_banner_moves_actions_to_sidebar_and_uses_decorative_art():
    source = APP_SOURCE.read_text(encoding="utf-8")
    styles = APP_STYLES.read_text(encoding="utf-8")

    banner = source[source.index('<header className="history-banner">'):source.index("</header>", source.index('<header className="history-banner">'))]
    assert "连接手机" not in banner
    assert "刷新" not in banner
    assert 'className="history-banner-art"' in banner
    assert 'className="history-banner-wave"' in banner
    assert 'className="nav-item active" onClick={() => void loadHistory(false)}' in source
    assert 'className="nav-trailing"' in source
    assert ".history-banner::after" not in styles
    assert ".history-banner-art" in styles
    assert "@keyframes banner-breathe" in styles


def test_history_list_loads_next_page_automatically_near_scroll_end():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "useRef" in source
    assert "const handleHistoryScroll" in source
    assert "scrollHeight - scrollTop - clientHeight <= 96" in source
    assert "onScroll={handleHistoryScroll}" in source
    assert "loadHistory(true)" in source
    assert "再加载 30 条" not in source


def test_manage_dialog_exposes_complete_update_flow():
    source = APP_SOURCE.read_text(encoding="utf-8")
    rust_source = (ROOT / "desktop" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "立即更新" in source
    assert "'/desktop/update/prepare'" in source
    assert "invoke('install_update'" in source
    assert "fn install_update(" in rust_source
    assert '"/S"' not in rust_source
    assert "-ArgumentList '/S'" in rust_source
    assert "CREATE_NO_WINDOW" in rust_source
    assert "previous application restarted after failure" in rust_source
    assert "installer completion marker timeout" in rust_source
    assert "expectedVersion: prepared.version" in source


def test_app_checks_for_updates_automatically_and_opens_prompt():
    source = APP_SOURCE.read_text(encoding="utf-8")

    # 更新源改为 GitHub 后自动检查必须收敛：未认证的 releases API 只有 60 次/小时，
    # 原先 5 分钟一轮会把额度打满，服务端另有 30 分钟 TTL 缓存兜底。
    assert "const AUTO_UPDATE_INTERVAL_MS = 30 * 60 * 1000" in source
    assert "const AUTO_UPDATE_FOCUS_THROTTLE_MS = 5 * 60 * 1000" in source
    assert "window.setInterval(checkForUpdate, AUTO_UPDATE_INTERVAL_MS)" in source
    assert "window.addEventListener('focus', checkAfterFocus)" in source
    assert "dismissedUpdateVersionRef.current !== response.result.version" in source
    assert "setAvailableUpdate(response.result)" in source
    assert "<UpdateDialog" in source
    assert 'title="发现新版本"' in source
    assert "下载并更新" in source


def test_sidebar_surfaces_update_entry_point():
    """左下角常驻更新入口：发现新版本即可一键更新。"""
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'className="update-indicator"' in source
    assert "有新版本 {availableUpdate.version}" in source
    assert "点击立即更新" in source
    assert "onClick={() => void installAvailableUpdate()}" in source


def test_version_label_reads_from_runtime_not_hardcoded():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "桌面版 v{bridge?.version || '—'}" in source
    assert "桌面版 v0.12.2" not in source


def test_manage_dialog_hides_fixed_update_source():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "更新源 URL" not in source
    assert "setUpdateUrl" not in source
    assert "update_url: updateUrl" not in source
    assert "更新源由发布端统一管理" in source
