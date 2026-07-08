import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "gui_app.py"


def load_app():
    spec = importlib.util.spec_from_file_location("gui_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_html_page_has_chinese_to_english_button():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="translate"' in page
    assert "中译英" in page
    assert "translateText" in page
    assert "api.mymemory.translated.net" in page
    assert 'id="send"' in page


def test_html_page_has_file_upload_to_clipboard_controls():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="fileInput"' in page
    assert 'id="uploadFiles"' in page
    assert "文件剪贴板" in page
    assert "uploadFilesToClipboard" in page
    assert '"/files/clipboard"' in page


def test_html_page_uses_modern_file_picker_component():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="fileDropzone"' in page
    assert 'class="file-dropzone"' in page
    assert 'id="chooseFiles"' in page
    assert 'id="clearFiles"' in page
    assert 'id="fileList"' in page
    assert 'id="fileSummary"' in page
    assert 'class="file-input-native"' in page
    assert "selectedFiles" in page
    assert "openFilePicker" in page
    assert "showOpenFilePicker" in page
    assert "setSelectedFiles" in page
    assert "renderSelectedFiles" in page
    assert '"dragover"' in page
    assert '"drop"' in page


def test_html_page_uses_clean_tool_layout():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'class="app-shell"' in page
    assert 'class="tool-card"' in page
    assert 'class="action-row"' in page
    assert "输入内容" in page


def test_html_page_uses_polished_visual_shell_without_web_network_status():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert "visual-backdrop" in page
    assert "appShellIn" in page
    assert 'id="introSplash"' not in page
    assert 'class="intro-card"' not in page
    assert 'class="hero-panel"' not in page
    assert 'class="network-card"' not in page
    assert 'id="accessLink"' not in page
    assert 'id="copyLink"' not in page
    assert 'id="status"' not in page
    assert "局域网输入桥已就绪" not in page
    assert "服务在线" not in page
    assert "copyAccessLink" not in page
    assert "refreshStatus" not in page
    assert 'class="server"' not in page


def test_html_page_uses_paper_image_background_with_motion():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert "data:image/jpeg;base64," in page
    assert "paper-stage" in page
    assert "paperDrift" in page
    assert "paperLightSweep" in page


def test_html_page_starts_function_area_with_compact_input_drawer():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="inputDrawer"' in page
    assert 'class="input-drawer"' in page
    assert "drawer-summary" in page
    assert 'class="compact-input"' in page
    assert 'id="toggleInputSize"' in page
    assert 'id="toggleAssistTools"' in page
    assert 'id="toggleFileTools"' in page
    assert 'id="assistTools" class="quick-actions collapsible-panel" hidden' in page
    assert 'id="fileToolsPanel" class="file-tools collapsible-panel" hidden' in page
    assert "toggleInputSize" in page
    assert "togglePanel" in page
    assert "setPanelVisible" in page
    assert "input-expanded" in page
    assert "introSplash.remove" not in page
    assert "introExit" not in page
    assert "<details" not in page
    assert "<summary" not in page


def test_html_page_uses_only_expand_button_for_input_height():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="toggleInputSize"' in page
    assert "展开输入框" in page
    assert 'id="inputHeightRange"' not in page
    assert 'id="inputResizeGrip"' not in page
    assert 'id="inputHeightValue"' not in page
    assert "applyInputHeight" not in page
    assert "beginInputResize" not in page
    assert "--input-height" not in page


def test_html_page_adapts_file_picker_for_mobile_and_local_share():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert "isMobileClipboardMode" in page
    assert "isLocalShareMode" in page
    assert "shouldLoadSharedFiles" in page
    assert "applyFileMode" in page
    assert 'data-file-mode' in page
    assert "从相册或文件选择" in page
    assert 'id="imageInput"' in page
    assert 'id="documentInput"' in page
    assert 'id="chooseImages"' in page
    assert 'id="chooseDocuments"' in page
    assert "选图片/相册" in page
    assert "选文档/文件" in page
    assert ".pdf,.doc,.docx" in page
    assert "image/heic" in page
    assert "发布给手机下载" in page
    assert '"/files/share"' in page
    assert "loadSharedFiles" in page
    assert 'id="sharedFilesPanel"' in page
    assert 'id="sharedFilesList"' in page
    assert 'id="refreshSharedFiles"' in page
    assert "文件缓冲区" in page
    assert "文件缓冲区为空。电脑发布文件后会显示在这里。" in page
    assert "body[data-file-mode=\"mobile-clipboard\"] .shared-files-panel" not in page
    assert "return true;" in page
    assert "if (shouldLoadSharedFiles()) loadSharedFiles();" in page
    assert "setPanelVisible(fileToolsPanelEl, toggleFileToolsBtn, true);\n      for (const file of files.slice" not in page


def test_mobile_file_selection_waits_for_send_button_to_paste():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert "uploadFilesToPaste" in page
    assert '"/files/paste"' in page
    assert "if (selectedFiles.length && !isLocalShareMode())" in page
    assert "setMessage(\"文件已加入待发送，点击发送后粘贴到电脑。\", \"ok\");" in page
    assert "if (isMobileClipboardMode() && selectedFiles.length) uploadFilesToClipboard();" not in page
    assert "if (isMobileClipboardMode() && selectedFiles.length) uploadFilesToPaste();" not in page


def test_html_page_removes_newline_and_enter_delay_controls():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="newline"' not in page
    assert 'id="enterDelay"' not in page
    assert "末尾加换行" not in page
    assert "回车延时" not in page
    assert "add_newline: false" in page
    assert "enter_delay_sec: 0.5" in page


def test_html_page_groups_actions_by_task_priority():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert "editor-head" in page
    assert 'class="quick-actions collapsible-panel"' in page
    assert 'class="mobile-tool-switches"' in page
    assert 'class="tool-toggle"' in page
    assert 'class="option-grid"' in page
    assert 'class="send-panel"' in page
    assert 'class="primary-action"' in page
    assert 'class="ghost-button"' in page
    assert "润色区" in page


def test_html_page_places_send_before_file_tools_on_mobile():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    send_index = page.index('class="send-panel"')
    message_index = page.index('id="message"')
    file_tools_index = page.index('class="file-tools collapsible-panel"')
    shared_files_index = page.index('id="sharedFilesPanel"')

    assert send_index < message_index < file_tools_index < shared_files_index


def test_html_page_does_not_show_clipboard_history_panel():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="historyPanel"' not in page
    assert 'id="historyList"' not in page
    assert "loadClipboardHistory" not in page
    assert "renderClipboardHistory" not in page
    assert '"/history"' not in page
