import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "gui_app.py"


def load_app():
    spec = importlib.util.spec_from_file_location("gui_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_prompt_library_has_core_modes():
    app = load_app()

    library = app.default_prompt_library()
    modes = {mode["id"] for mode in library["modes"]}

    assert {"dialog", "raw", "image", "code", "writing"}.issubset(modes)
    assert library["source_catalogs"][0]["name"] == "prompts.chat"


def test_enrich_prompt_requires_minimax_api_key():
    app = load_app()

    try:
        app.enrich_prompt(
            "帮我写一个销售邮件",
            "dialog",
            app.default_prompt_library(),
            api_config={"api_key": "", "base_url": "https://api.minimaxi.com/v1", "model": "MiniMax-M3"},
        )
    except RuntimeError as exc:
        assert "MiniMax API Key" in str(exc)
    else:
        raise AssertionError("enrich_prompt should require a MiniMax API key")


def test_enrich_prompt_calls_minimax_and_returns_model_text():
    app = load_app()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "请作为销售专家，写一封面向企业客户的销售邮件。"
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    result = app.enrich_prompt(
        "帮我写一个销售邮件",
        "dialog",
        app.default_prompt_library(),
        api_config={
            "api_key": "test-key",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3",
        },
        transport=fake_urlopen,
    )

    assert result["mode"] == "dialog"
    assert result["provider"] == "minimax"
    assert result["text"] == "请作为销售专家，写一封面向企业客户的销售邮件。"
    assert result["changed"] is True
    assert captured["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "MiniMax-M3"
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["messages"][0]["role"] == "system"
    assert "帮我写一个销售邮件" in captured["body"]["messages"][1]["content"]


def test_enrich_prompt_normalizes_structured_question_result():
    app = load_app()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "question",
                                        "question": "你要测试哪个方向？",
                                        "candidate": "",
                                        "mode": "dialog",
                                        "reason": "原始需求缺少测试方向。",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")

    result = app.enrich_prompt(
        "测试",
        "dialog",
        app.default_prompt_library(),
        api_config={
            "api_key": "test-key",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3",
        },
        transport=lambda request, timeout: FakeResponse(),
    )

    assert result["action"] == "question"
    assert result["question"] == "你要测试哪个方向？"
    assert result["candidate"] == ""
    assert result["text"] == "你要测试哪个方向？"


def test_auto_prompt_mode_is_recorded_and_resolved_to_concrete_mode():
    app = load_app()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "请帮我优化下面这段 Python 代码。"}}]},
                ensure_ascii=False,
            ).encode("utf-8")

    result = app.enrich_prompt(
        "优化这段 Python 代码",
        "auto",
        app.default_prompt_library(),
        api_config={
            "api_key": "test-key",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3",
        },
        transport=lambda request, timeout: FakeResponse(),
    )

    assert result["requested_mode"] == "auto"
    assert result["mode"] == "code"
    assert result["label"] == "代码提示词"


def test_minimax_key_file_takes_priority_over_generic_openai_key(tmp_path, monkeypatch):
    app = load_app()
    key_file = tmp_path / "minimax_api_key.txt"
    key_file.write_text("file-minimax-key", encoding="utf-8")
    monkeypatch.setattr(app, "MINIMAX_API_KEY_FILE", key_file)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "bad")

    config = app.read_minimax_config()

    assert config["api_key"] == "file-minimax-key"


def test_prompt_enrichment_message_requires_semantic_judgment_before_rewrite():
    app = load_app()
    mode = app.find_prompt_mode("dialog", app.default_prompt_library())

    messages = app.build_prompt_enrichment_messages("写一个测试", mode)
    system = messages[0]["content"]

    assert "先判断原始需求是否真的需要润色" in system
    assert "不要把简单测试、短命令、按钮名、关键词" in system
    assert "不要过度扩写" in system
    assert "表达一个想法但表达不清楚" in system


def test_html_page_has_prompt_enrich_controls():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert 'id="promptMode"' in page
    assert 'id="enrichPrompt"' in page
    assert "润色提示词" in page
    assert "enrichPromptText" in page


def test_html_page_has_prompt_workbench_and_auto_mode():
    app = load_app()

    page = app.html_page("access-key", "http://127.0.0.1:8765/?key=access-key")

    assert '<option value="auto"' in page
    assert 'id="promptWorkbench"' in page
    assert 'id="promptQuestion"' in page
    assert 'id="promptAnswer"' in page
    assert 'id="promptCandidate"' in page
    assert 'id="sendPromptAnswer"' in page
    assert 'id="acceptPromptResult"' in page
    assert "renderPromptWorkbench(data.result)" in page
    assert "textEl.value = data.result.text;" not in page
