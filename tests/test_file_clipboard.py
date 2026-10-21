import importlib.util
from datetime import datetime
from io import BytesIO
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
    assert saved.parent == tmp_path / "files"
    assert saved.read_bytes() == b"PDFDATA"


def test_streaming_multipart_upload_has_no_configured_size_limit(tmp_path):
    app = load_app()
    boundary = "----bridge-stream-test"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="key"\r\n\r\n'
        "secret\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="long-video.mp4"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode("utf-8") + (b"video-data" * 4096) + f"\r\n--{boundary}--\r\n".encode("utf-8")

    result = app.parse_multipart_upload_stream(
        BytesIO(body),
        len(body),
        f"multipart/form-data; boundary={boundary}",
        tmp_path,
    )

    assert not hasattr(app, "MAX_UPLOAD_BYTES")
    assert result["key"] == "secret"
    assert result["files"][0]["bytes"] == len(b"video-data" * 4096)
    assert Path(result["files"][0]["path"]).read_bytes() == b"video-data" * 4096


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
    assert result["items"][0]["type"] == "file"
    history = app.list_clipboard_history()
    assert history[0]["action"] == "share"
    assert history[0]["files"][0]["path"] == str((share_dir / "report.txt").resolve())


def test_publish_text_for_mobile_creates_copyable_feed_item_without_txt_file(tmp_path, monkeypatch):
    app = load_app()
    share_dir = tmp_path / "share"
    history_file = tmp_path / "clipboard_history.json"
    monkeypatch.setattr(app, "HISTORY_FILE", history_file)

    result = app.publish_text_for_mobile_download("手机可下载的文字", share_dir=share_dir)

    assert result["texts"] == 1
    published = result["published"][0]
    assert published["type"] == "text"
    assert published["text"] == "手机可下载的文字"
    assert list(share_dir.glob("*.txt")) == []
    assert result["items"][0]["text"] == "手机可下载的文字"
    history = app.list_clipboard_history()
    assert history[0]["action"] == "share"
    assert history[0]["type"] == "text"


def test_mobile_share_feed_lists_text_files_and_legacy_files(tmp_path):
    app = load_app()
    share_dir = tmp_path / "share"
    share_dir.mkdir()
    feed_file = tmp_path / "feed.json"
    indexed_file = share_dir / "indexed.pdf"
    legacy_file = share_dir / "legacy.docx"
    indexed_file.write_bytes(b"pdf")
    legacy_file.write_bytes(b"docx")
    app.write_mobile_share_feed(
        [
            {"id": "text-1", "type": "text", "text": "复制我", "chars": 3, "mtime": 3_000_000_000},
            {
                "id": "file-1",
                "type": "file",
                "name": "indexed.pdf",
                "bytes": 3,
                "mtime": 2_000_000_000,
                "content_type": "application/pdf",
            },
        ],
        share_dir,
        feed_file,
    )

    items = app.list_shared_items(share_dir, feed_file)

    assert [item["type"] for item in items] == ["text", "file", "file"]
    assert items[0]["text"] == "复制我"
    assert {item.get("name") for item in items[1:]} == {"indexed.pdf", "legacy.docx"}


def test_shared_file_inline_policy_blocks_executable_web_content():
    app = load_app()

    assert app.can_inline_shared_content("application/pdf") is True
    assert app.can_inline_shared_content("image/jpeg") is True
    assert app.can_inline_shared_content("video/mp4") is True
    assert app.can_inline_shared_content("text/plain; charset=utf-8") is True
    assert app.can_inline_shared_content("text/html") is False
    assert app.can_inline_shared_content("image/svg+xml") is False
    assert app.can_inline_shared_content("application/octet-stream") is False


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
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video bytes")
    video_record = app.record_file_history(
        [{"name": "clip.mp4", "path": str(video_path), "bytes": 3072, "content_type": "video/mp4"}],
        now=3,
    )
    media_record = app.record_file_history(
        [
            {"name": "photo.png", "path": str(tmp_path / "photo.png"), "bytes": 1024, "content_type": "image/png"},
            {"name": "clip.mov", "path": str(tmp_path / "clip.mov"), "bytes": 4096, "content_type": "video/quicktime"},
        ],
        now=4,
    )
    mixed_record = app.record_file_history(
        [
            {"name": "photo.png", "path": str(tmp_path / "photo.png"), "bytes": 1024, "content_type": "image/png"},
            {"name": "report.pdf", "path": str(tmp_path / "report.pdf"), "bytes": 4096, "content_type": "application/pdf"},
        ],
        now=5,
    )

    assert app.history_record_preview(text_record)["kind"] == "文字"
    assert app.history_record_preview(text_record)["info"].endswith("字")
    assert app.history_record_preview(image_record) == {
        "kind": "图片",
        "preview": "photo.jpg",
        "info": "1 张 | 2.0 KB",
    }
    assert app.history_record_preview(video_record) == {
        "kind": "视频",
        "preview": "clip.mp4",
        "info": "1 个 | 3.0 KB",
    }
    assert app.history_record_preview(media_record)["kind"] == "媒体"
    assert "图片 1 张" in app.history_record_preview(media_record)["info"]
    assert "视频 1 个" in app.history_record_preview(media_record)["info"]
    assert app.history_record_preview(mixed_record)["kind"] == "混合"
    assert "图片 1 张" in app.history_record_preview(mixed_record)["info"]
    assert app.is_video_history_file({"name": "movie.mov", "content_type": ""})
    assert app.is_gallery_history_file({"name": "movie.webm", "content_type": "video/webm"})
    assert app.first_image_history_path(image_record) == image_path
    assert app.first_gallery_history_path(video_record) == video_path


def test_format_history_timestamp_includes_full_date_and_minute():
    app = load_app()

    local_timestamp = datetime(2026, 7, 7, 9, 40).timestamp()
    assert app.format_history_timestamp(local_timestamp) == "2026年07月07日 09:40"
    assert app.format_history_timestamp(None) == "时间未知"


def test_connection_self_check_includes_health_url_without_access_key():
    app = load_app()

    report = app.build_connection_self_check(8765, True, "192.168.1.63")

    assert "服务状态：运行中" in report
    assert "电脑局域网入口：192.168.1.63:8765" in report
    assert "手机健康检查：http://192.168.1.63:8765/health" in report
    assert "AP 隔离" in report
    assert ("本地网络权限" if app.IS_MACOS else "防火墙") in report
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
    assert [item["id"] for item in app.search_clipboard_history(category="text")] == [text_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history(category="image")] == [image_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history(category="file")] == [pdf_record["id"]]
    assert [item["id"] for item in app.search_clipboard_history("screen", category="image")] == [image_record["id"]]
    assert app.search_clipboard_history("screen", category="file") == []
    assert app.search_clipboard_history("不存在") == []


def test_history_preview_pages_global_archive_thirty_records_at_a_time(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")

    for index in range(60):
        app.record_text_history(f"记录 {index}", now=index + 1)

    records = app.search_clipboard_history()

    assert app.HISTORY_WINDOW_LIMIT == 30
    assert len(records) == 30
    assert records[0]["text"] == "记录 59"
    assert records[-1]["text"] == "记录 30"
    global_results = app.search_clipboard_history("记录", limit=None)
    assert len(global_results) == 60
    assert global_results[-1]["text"] == "记录 0"


def test_history_archive_writes_jsonl_and_categorizes_uploaded_media(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")
    archive_dir = tmp_path / "history_archive"

    text_record = app.record_text_history("归档检索文字", now=1)
    image_dir = app.history_file_category_dir("photo.jpg", "image/jpeg", archive_dir)
    video_dir = app.history_file_category_dir("clip.mp4", "video/mp4", archive_dir)
    file_dir = app.history_file_category_dir("report.pdf", "application/pdf", archive_dir)

    assert image_dir == archive_dir / "images"
    assert video_dir == archive_dir / "videos"
    assert file_dir == archive_dir / "files"
    text_lines = (archive_dir / "texts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(text_lines) == 1
    assert "归档检索文字" in text_lines[0]

    app.clear_clipboard_history()
    results = app.search_clipboard_history("归档检索", limit=None)
    assert [item["id"] for item in results] == [text_record["id"]]


def test_history_archive_backfill_is_idempotent(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")
    text_record = {
        "id": "legacy-text",
        "type": "text",
        "text": "旧文字",
        "preview": "旧文字",
        "chars": 3,
        "action": "send",
        "ts": 1,
    }
    file_record = {
        "id": "legacy-file",
        "type": "file",
        "files": [{"name": "old.pdf", "path": str(tmp_path / "old.pdf"), "bytes": 1}],
        "action": "paste",
        "ts": 2,
    }
    app.write_history_file([file_record, text_record])

    assert app.backfill_history_archive() == {"text": 1, "files": 1}
    assert app.backfill_history_archive() == {"text": 0, "files": 0}
    assert len(app.read_history_jsonl(tmp_path / "history_archive" / "texts.jsonl")) == 1
    assert len(app.read_history_jsonl(tmp_path / "history_archive" / "files.jsonl")) == 1
    assert {path.name for path in (tmp_path / "history_archive").iterdir() if path.is_dir()} == {
        "images",
        "videos",
        "files",
    }


def test_find_history_record_includes_records_only_kept_in_global_archive(tmp_path, monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "clipboard_history.json")
    archive_dir = tmp_path / "history_archive"
    image_path = archive_dir / "images" / "archived-photo.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image")
    archived = {
        "id": "archived-file",
        "type": "file",
        "files": [
            {
                "name": image_path.name,
                "path": str(image_path),
                "bytes": image_path.stat().st_size,
                "content_type": "image/jpeg",
            }
        ],
        "ts": 1,
    }
    app.append_history_jsonl(archive_dir / "files.jsonl", archived)

    assert app.find_history_record("archived-file")["id"] == "archived-file"
    assert app.first_image_history_path(app.find_history_record("archived-file")) == image_path
