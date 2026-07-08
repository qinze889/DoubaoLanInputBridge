import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "gui_app.py"


def load_app():
    spec = importlib.util.spec_from_file_location("gui_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sanitize_upload_filename_removes_path_parts():
    app = load_app()

    assert app.sanitize_upload_filename(r"..\demo.pdf") == "demo.pdf"
    assert app.sanitize_upload_filename("../../a:b?.docx") == "a_b_.docx"


def test_parse_multipart_upload_saves_files_and_key(tmp_path):
    app = load_app()
    boundary = "----bridge-test"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="key"\r\n\r\n'
        "secret\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="note.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "PDFDATA\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    result = app.parse_multipart_upload(
        body,
        f"multipart/form-data; boundary={boundary}",
        tmp_path,
    )

    assert result["key"] == "secret"
    assert len(result["files"]) == 1
    saved = Path(result["files"][0]["path"])
    assert saved.name == "note.pdf"
    assert saved.read_bytes() == b"PDFDATA"


def test_build_file_drop_data_uses_unicode_file_list():
    app = load_app()

    data = app.build_file_drop_data([Path(r"C:\tmp\a.pdf"), Path(r"C:\tmp\b.docx")])

    assert data[:4] == (20).to_bytes(4, "little")
    assert data[16:20] == (1).to_bytes(4, "little")
    assert "C:\\tmp\\a.pdf\0C:\\tmp\\b.docx\0\0".encode("utf-16le") in data


def test_paste_uploaded_files_pastes_one_file_at_a_time(tmp_path):
    app = load_app()
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    calls = []

    result = app.paste_uploaded_files(
        [
            {"path": str(first), "name": first.name},
            {"path": str(second), "name": second.name},
        ],
        set_files=lambda paths: calls.append(("files", [Path(path).name for path in paths])),
        paste=lambda: calls.append(("paste", None)),
        sleeper=lambda seconds: calls.append(("sleep", seconds)),
    )

    assert result["files"] == 2
    assert result["pastes"] == 2
    assert calls[0] == ("files", ["a.jpg"])
    assert calls[2] == ("paste", None)
    assert calls[4] == ("files", ["b.jpg"])
    assert calls[6] == ("paste", None)


def test_list_shared_files_returns_download_records(tmp_path):
    app = load_app()
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.docx"
    first.write_bytes(b"PDF")
    second.write_bytes(b"DOC")

    records = app.list_shared_files(tmp_path)

    assert {item["name"] for item in records} == {"a.pdf", "b.docx"}
    assert {item["bytes"] for item in records} == {3}


def test_resolve_shared_download_rejects_path_traversal(tmp_path):
    app = load_app()
    inside = tmp_path / "ok.txt"
    outside = tmp_path.parent / "outside.txt"
    inside.write_text("ok", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")

    assert app.resolve_shared_download("ok.txt", tmp_path) == inside.resolve()

    try:
        app.resolve_shared_download("../outside.txt", tmp_path)
    except ValueError as exc:
        assert "文件不存在" in str(exc) or "非法文件名" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")


def test_publish_files_for_mobile_download_copies_files_and_records_history(tmp_path, monkeypatch):
    app = load_app()
    share_dir = tmp_path / "share"
    history_file = tmp_path / "clipboard_history.json"
    monkeypatch.setattr(app, "HISTORY_FILE", history_file)
    source = tmp_path / "report.txt"
    source.write_text("hello", encoding="utf-8")

    result = app.publish_files_for_mobile_download([source], share_dir=share_dir)

    assert result["files"] == 1
    assert result["published"][0]["name"] == "report.txt"
    assert (share_dir / "report.txt").read_text(encoding="utf-8") == "hello"
    assert result["items"][0]["name"] == "report.txt"
    history = app.list_clipboard_history()
    assert history[0]["action"] == "share"
    assert history[0]["files"][0]["path"] == str((share_dir / "report.txt").resolve())


def test_clipboard_history_records_text_files_pins_and_cleans_old_items(tmp_path, monkeypatch):
    app = load_app()
    history_file = tmp_path / "clipboard_history.json"
    monkeypatch.setattr(app, "HISTORY_FILE", history_file)
    now = 1_700_000_000
    old = now - (app.HISTORY_RETENTION_DAYS + 1) * 86400

    text_record = app.record_text_history(" 常用回复 ", action="send", now=old)
    file_path = tmp_path / "note.pdf"
    file_path.write_bytes(b"PDF")
    file_record = app.record_file_history(
        [{"name": "note.pdf", "path": str(file_path), "bytes": 3, "content_type": "application/pdf"}],
        action="paste",
        now=now,
    )
    app.set_history_pinned(text_record["id"], True)
    app.cleanup_history(now=now)
    records = app.list_clipboard_history()

    assert [item["type"] for item in records] == ["file", "text"]
    assert records[0]["id"] == file_record["id"]
    assert records[0]["files"][0]["name"] == "note.pdf"
    assert records[1]["pinned"] is True

    app.delete_history_item(file_record["id"])
    assert [item["id"] for item in app.list_clipboard_history()] == [text_record["id"]]

    app.clear_clipboard_history()
    assert app.list_clipboard_history() == []


def test_open_history_file_item_can_open_file_or_parent_folder(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")
    file_path = tmp_path / "report.txt"
    file_path.write_text("ok", encoding="utf-8")
    record = app.record_file_history([{"name": file_path.name, "path": str(file_path), "bytes": 2}], action="clipboard")
    opened = []

    result_file = app.open_history_file_item(record["id"], mode="file", opener=lambda path: opened.append(Path(path)))
    result_folder = app.open_history_file_item(record["id"], mode="folder", opener=lambda path: opened.append(Path(path)))

    assert result_file["path"] == str(file_path.resolve())
    assert result_folder["path"] == str(tmp_path.resolve())
    assert opened == [file_path.resolve(), tmp_path.resolve()]


def test_clipboard_history_limits_unpinned_records(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")
    monkeypatch.setattr(app, "MAX_HISTORY_ITEMS", 3)

    pinned = app.record_text_history("pinned", pinned=True, now=1)
    for index in range(5):
        app.record_text_history(f"text {index}", now=10 + index)

    records = app.list_clipboard_history()

    assert len(records) == 3
    assert pinned["id"] in {item["id"] for item in records}
    assert records[0]["text"] == "text 4"


def test_history_record_preview_describes_text_images_and_files(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")

    text_record = app.record_text_history("这是一段用于预览的文字", now=1)
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"not a real jpeg but exists for path selection")
    image_record = app.record_file_history(
        [{"name": "photo.jpg", "path": str(image_path), "bytes": 2048, "content_type": "image/jpeg"}],
        now=2,
    )
    mixed_record = app.record_file_history(
        [
            {"name": "photo.png", "path": str(tmp_path / "photo.png"), "bytes": 1024, "content_type": "image/png"},
            {"name": "report.pdf", "path": str(tmp_path / "report.pdf"), "bytes": 4096, "content_type": "application/pdf"},
        ],
        now=3,
    )

    assert app.history_record_preview(text_record)["kind"] == "文字"
    assert app.history_record_preview(text_record)["info"].endswith("字")
    assert app.history_record_preview(image_record) == {
        "kind": "图片",
        "preview": "photo.jpg",
        "info": "1 张 | 2.0 KB",
    }
    assert app.history_record_preview(mixed_record)["kind"] == "混合"
    assert "图片 1 张" in app.history_record_preview(mixed_record)["info"]
    assert app.first_image_history_path(image_record) == image_path


def test_format_history_timestamp_includes_full_date_and_minute():
    app = load_app()

    assert app.format_history_timestamp(1783388400) == "2026年07月07日 09:40"
    assert app.format_history_timestamp(None) == "时间未知"


def test_connection_self_check_includes_health_url_without_access_key():
    app = load_app()

    report = app.build_connection_self_check(8765, True, "192.168.1.63")

    assert "服务状态：运行中" in report
    assert "电脑局域网入口：192.168.1.63:8765" in report
    assert "手机健康检查：http://192.168.1.63:8765/health" in report
    assert "AP 隔离" in report
    assert "Windows 防火墙" in report
    assert "key=" not in report


def test_search_clipboard_history_matches_text_file_names_and_types(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")

    text_record = app.record_text_history("会议纪要：下周更新", now=1)
    image_path = tmp_path / "screen-shot.png"
    image_path.write_bytes(b"image")
    image_record = app.record_file_history(
        [{"name": "screen-shot.png", "path": str(image_path), "bytes": 5, "content_type": "image/png"}],
        now=2,
    )
    pdf_path = tmp_path / "contract.pdf"
    pdf_path.write_bytes(b"pdf")
    pdf_record = app.record_file_history(
        [{"name": "contract.pdf", "path": str(pdf_path), "bytes": 3, "content_type": "application/pdf"}],
        now=3,
    )

    assert [item["id"] for item in app.search_clipboard_history("会议")] == [text_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history("screen")] == [image_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history("pdf")] == [pdf_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history("文件 contract")] == [pdf_record["id"]]
    assert app.search_clipboard_history("不存在") == []
