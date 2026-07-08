import argparse
import csv
import json
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_SOURCE = "https://raw.githubusercontent.com/f/prompts.chat/main/prompts.csv"


def load_library(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": 1, "source_catalogs": [], "modes": [], "external_prompts": []}


def import_prompts(source_url: str, limit: int) -> list[dict]:
    request = Request(source_url, headers={"User-Agent": "DoubaoLanInputBridge-prompt-importer"})
    with urlopen(request, timeout=20) as response:
        content = response.read().decode("utf-8-sig")
    rows = csv.DictReader(content.splitlines())
    prompts = []
    for index, row in enumerate(rows):
        if limit and index >= limit:
            break
        title = (row.get("act") or row.get("title") or "").strip()
        prompt = (row.get("prompt") or "").strip()
        if not title or not prompt:
            continue
        prompts.append(
            {
                "id": f"prompts-chat-{index + 1}",
                "title": title,
                "category": "role_prompt",
                "source": "prompts.chat",
                "prompt": prompt,
            }
        )
    return prompts


def main() -> int:
    parser = argparse.ArgumentParser(description="Import prompts.chat CSV into a local prompt_library.json")
    parser.add_argument("library", type=Path, help="Path to prompt_library.json")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    library = load_library(args.library)
    existing_ids = {item.get("id") for item in library.get("external_prompts", [])}
    imported = [item for item in import_prompts(args.source, args.limit) if item["id"] not in existing_ids]
    library.setdefault("external_prompts", []).extend(imported)
    args.library.parent.mkdir(parents=True, exist_ok=True)
    args.library.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"imported={len(imported)} path={args.library}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
