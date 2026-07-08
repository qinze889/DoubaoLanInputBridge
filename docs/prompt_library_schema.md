# 本地提示词模式库结构

默认位置：

```text
%LOCALAPPDATA%\DoubaoLanInputBridge\prompt_library.json
```

这个文件由程序首次使用“润色提示词”或“打开词库目录”时自动创建。你可以直接编辑它，把自己的提示词模式、词库、外部导入提示词放进去。

从 `0.4.0` 起，“润色提示词”不再只拼接本地模板，而是把当前模式转换为 system prompt，再调用 MiniMax OpenAI 兼容接口生成结果。本地库负责管理分类、角色、目标、风格词和输出格式。

MiniMax Key 不写入这个 JSON。程序会读取环境变量 `MINIMAX_API_KEY` / `OPENAI_API_KEY`，或读取同目录下的 `minimax_api_key.txt`。

## 顶层字段

```json
{
  "version": 1,
  "source_catalogs": [],
  "modes": [],
  "external_prompts": []
}
```

- `source_catalogs`：记录外部提示词库来源，例如 GitHub 仓库和许可证。
- `modes`：本工具实际用于构造 MiniMax system prompt 的模式库。
- `external_prompts`：从外部库导入的原始提示词，供后续筛选、复制、二次整理。

## modes

每个模式代表一种润色方向：

```json
{
  "id": "dialog",
  "label": "对话提示词",
  "role": "资深对话助手",
  "goal": "把用户的想法整理成适合对话模型执行的清晰指令。",
  "style_terms": ["明确目标", "补齐上下文", "列出约束"],
  "output_format": "先给结论，再给步骤。"
}
```

当前内置模式：

- `dialog`：对话提示词
- `raw`：原始提示词
- `image`：图像提示词
- `code`：代码提示词
- `writing`：写作提示词

## 从 prompts.chat 导入

```powershell
C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe scripts\import_prompts_chat.py "$env:LOCALAPPDATA\DoubaoLanInputBridge\prompt_library.json"
```

默认导入前 200 条到 `external_prompts`。导入后不会自动改变润色逻辑；建议你从里面挑出常用结构，整理到 `modes` 里。
